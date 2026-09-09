//! Revisioned, nonblocking interaction transactions. Native remains the layer owner.
use super::*;

const MAX_PENDING: usize = 256;
const MAX_LINE: usize = 1024 * 1024;
// A failed companion must not retain synthetic keys indefinitely. This is a
// failure-containment deadline, not the normal input-latency acceptance budget.
const ACK_DEADLINE: Duration = Duration::from_millis(500);

#[derive(Clone, Copy)]
enum Work {
    Event(u64, MatrixEvent),
    End(u64),
}
enum LayerChange {
    Apply(LayerAction, bool, PressIdentity),
    Consume,
    Lock(Option<usize>, bool),
}

pub(super) struct Delegate {
    connection: Option<StreamClient>,
    pending: Option<(Value, Instant)>,
    queue: VecDeque<Work>,
    sequence: u64,
    started: Instant,
    next_tick: Option<Duration>,
    owned_injections: HashSet<String>,
    injection_sources: HashMap<String, u64>,
    scheduled: VecDeque<(Instant, String, String, bool, InjectedRoute, u64)>,
    schedule_context: Option<bool>,
    ended_sources: HashSet<u64>,
    allowed_sources: HashSet<u64>,
    last_ack: Option<Value>,
    owned_layers: HashSet<(usize, PressIdentity)>,
    pub(super) max_queue: usize,
    pub(super) last_error: String,
}

impl Delegate {
    pub(super) fn invalidate(
        &mut self,
        core: &mut Core,
        config: &Config,
        broker: &UnixDatagram,
        error: &mut String,
    ) {
        self.fail(core, config, broker, error, "owner_transition");
        core.counters.delegate_errors = core.counters.delegate_errors.saturating_sub(1);
        self.last_error.clear();
    }
    pub(super) fn owned_key_event(
        &mut self,
        core: &mut Core,
        config: &Config,
        request: &Value,
        broker: &UnixDatagram,
        error: &mut String,
    ) -> Value {
        let Some(source) = request["source"].as_u64() else {
            return json!({"result":"error","error":"invalid_delegate_source"});
        };
        let Some(id) = request["id"]
            .as_str()
            .filter(|id| id.starts_with("macro:") && id.len() <= 1024)
        else {
            return json!({"result":"error","error":"invalid_delegate_injection_id"});
        };
        let Some(action) = request["action"].as_str() else {
            return json!({"result":"error","error":"action_required"});
        };
        let Some(press) = request["is_press"].as_bool() else {
            return json!({"result":"error","error":"is_press_required"});
        };
        if !self.allowed_sources.contains(&source)
            || self.ended_sources.contains(&source)
            || self
                .injection_sources
                .get(id)
                .is_some_and(|owner| *owner != source)
        {
            return json!({"result":"error","error":"delegate_source_expired"});
        }
        for report in core.end_guarded_tap("delegate_input") {
            emit_report(broker, config, core, &report, error);
        }
        match core.apply_injected_key_event_with_route(id, action, press, InjectedRoute::Normal) {
            Ok(reports) => {
                let count = reports.len();
                for report in reports {
                    emit_report(broker, config, core, &report, error);
                }
                if press {
                    self.owned_injections.insert(id.into());
                    self.injection_sources.insert(id.into(), source);
                } else {
                    self.owned_injections.remove(id);
                    self.injection_sources.remove(id);
                }
                json!({"result":"ok","emitted":count})
            }
            Err(reason) => json!({"result":"error","error":reason}),
        }
    }
    pub(super) fn metrics(&self) -> Value {
        json!({"queue_depth":self.queue.len(),"max_queue_depth":self.max_queue,
        "pending":self.pending.is_some(),"scheduled_events":self.scheduled.len(),"last_error":self.last_error})
    }
    pub(super) fn new() -> Self {
        Self {
            connection: None,
            pending: None,
            queue: VecDeque::new(),
            sequence: 0,
            started: Instant::now(),
            next_tick: None,
            owned_injections: HashSet::new(),
            owned_layers: HashSet::new(),
            injection_sources: HashMap::new(),
            scheduled: VecDeque::new(),
            schedule_context: None,
            ended_sources: HashSet::new(),
            allowed_sources: HashSet::new(),
            last_ack: None,
            max_queue: 0,
            last_error: String::new(),
        }
    }

    fn known_native_release(core: &Core, source: u64, event: MatrixEvent) -> bool {
        !event.press
            && core
                .pressed_matrix
                .get(&(source, event.row, event.col))
                .is_some_and(|a| !matches!(a, Action::Delegated(_)))
    }

    pub(super) fn event(
        &mut self,
        core: &mut Core,
        config: &Config,
        source: u64,
        event: MatrixEvent,
        broker: &UnixDatagram,
        error: &mut String,
    ) {
        for report in core.end_guarded_tap("input_transition") {
            emit_report(broker, config, core, &report, error);
        }
        if (self.pending.is_some() || !self.scheduled.is_empty())
            && !Self::known_native_release(core, source, event)
        {
            if self.queue.len() == MAX_PENDING {
                self.fail(core, config, broker, error, "delegate_queue_full");
                return;
            }
            self.queue.push_back(Work::Event(source, event));
            self.max_queue = self.max_queue.max(self.queue.len());
            return;
        }
        self.execute_event(core, config, source, event, broker, error);
    }

    fn execute_event(
        &mut self,
        core: &mut Core,
        config: &Config,
        source: u64,
        event: MatrixEvent,
        broker: &UnixDatagram,
        error: &mut String,
    ) {
        let identity = (source, event.row, event.col);
        let resolve_context = event.press && (core.force_delegate_all || core.delegate_active());
        let action = if event.press {
            Some(core.resolve_action_string(event.row, event.col).to_owned())
        } else {
            core.pressed_matrix.get(&identity).and_then(|a| {
                if let Action::Delegated(a) = a {
                    Some(a.clone())
                } else {
                    None
                }
            })
        };
        let outcome = core.apply_source_event(source, event);
        if outcome.delegate_packet.is_some() {
            if event.press {
                self.allowed_sources.insert(source);
            }
            let mut request = self.envelope(core, "delegate_event");
            request["source"] = json!(source);
            request["row"] = json!(event.row);
            request["col"] = json!(event.col);
            request["is_press"] = json!(event.press);
            request["resolve_context"] = json!(resolve_context);
            request["action"] = if resolve_context {
                Value::Null
            } else {
                json!(action)
            };
            self.send(core, config, request, broker, error);
        }
        if let Some(packet) = outcome.tap_packet {
            tap_matrix_packet(core, config, packet);
        }
        let start = core
            .counters
            .reports_emitted
            .saturating_sub(outcome.reports.len() as u64)
            + 1;
        for (offset, report) in outcome.reports.iter().enumerate() {
            if let Err(err) = write_preview_log(config, start + offset as u64, &event, report) {
                eprintln!("warning: {err}");
            }
            emit_report(broker, config, core, report, error);
        }
    }

    fn envelope(&mut self, core: &Core, kind: &str) -> Value {
        self.sequence += 1;
        json!({"t":kind,"protocol":2,"event_id":self.sequence,"owner_epoch":core.owner_epoch,
            "keymap_revision":core.keymap_revision,"layer_revision":core.layer_revision,
            "layer_state":core.layer_snapshot(),"layers":core.layers,"now_ms":self.started.elapsed().as_secs_f64()*1000.0})
    }

    fn send(
        &mut self,
        core: &mut Core,
        config: &Config,
        request: Value,
        broker: &UnixDatagram,
        error: &mut String,
    ) {
        if self.connection.is_none() {
            let connected = config
                .delegate_socket
                .as_ref()
                .and_then(|path| connect_unix_nonblocking(path).ok());
            let Some(stream) = connected else {
                self.fail(core, config, broker, error, "delegate_unavailable");
                return;
            };
            if stream.set_nonblocking(true).is_err() {
                self.fail(core, config, broker, error, "delegate_nonblocking_failed");
                return;
            }
            self.connection = Some(StreamClient::new(stream));
        }
        let client = self.connection.as_mut().unwrap();
        client
            .output
            .extend_from_slice(request.to_string().as_bytes());
        client.output.push(b'\n');
        self.pending = Some((request, Instant::now()));
        core.delegate_pending = true;
        if flush_pending(&mut client.stream, &mut client.output).is_err() {
            self.fail(core, config, broker, error, "delegate_write_failed");
        }
    }

    pub(super) fn end_source(
        &mut self,
        core: &mut Core,
        config: &Config,
        source: u64,
        broker: &UnixDatagram,
        error: &mut String,
    ) {
        core.coalesce_pending_reports();
        self.allowed_sources.remove(&source);
        let owned_layers: Vec<_> = self
            .owned_layers
            .iter()
            .filter(|(_, identity)| identity.0 == source)
            .copied()
            .collect();
        for (layer, identity) in owned_layers {
            core.apply_layer_action(
                LayerAction {
                    op: LayerOp::Momentary,
                    layer,
                },
                false,
                identity,
            );
            self.owned_layers.remove(&(layer, identity));
        }
        self.ended_sources.insert(source);
        self.scheduled.retain(|(_, _, _, _, _, id)| *id != source);
        let injections: Vec<_> = self
            .injection_sources
            .iter()
            .filter(|(_, id)| **id == source)
            .map(|(id, _)| id.clone())
            .collect();
        for id in injections {
            if let Ok(reports) = core.apply_injected_key_event_with_route(
                &id,
                "KC_NONE",
                false,
                InjectedRoute::Normal,
            ) {
                for report in reports {
                    emit_report(broker, config, core, &report, error);
                }
            }
            self.owned_injections.remove(&id);
            self.injection_sources.remove(&id);
        }
        self.queue.retain(|work| match work {
            Work::Event(id, _) | Work::End(id) => *id != source,
        });
        let mut held: Vec<_> = core
            .pressed_matrix
            .keys()
            .filter(|(id, _, _)| *id == source)
            .copied()
            .collect();
        held.sort_unstable();
        let had_delegate = held
            .iter()
            .any(|key| matches!(core.pressed_matrix.get(key), Some(Action::Delegated(_))))
            || self
                .pending
                .as_ref()
                .is_some_and(|(request, _)| request["source"].as_u64() == Some(source));
        for (_, row, col) in held {
            if Self::known_native_release(
                core,
                source,
                MatrixEvent {
                    press: false,
                    row,
                    col,
                },
            ) {
                self.execute_event(
                    core,
                    config,
                    source,
                    MatrixEvent {
                        press: false,
                        row,
                        col,
                    },
                    broker,
                    error,
                );
            } else {
                core.pressed_matrix.remove(&(source, row, col));
            }
        }
        if had_delegate || core.delegate_context {
            if self.pending.is_some() || !self.scheduled.is_empty() {
                self.queue.push_back(Work::End(source));
            } else {
                let mut request = self.envelope(core, "delegate_source_end");
                request["source"] = json!(source);
                self.send(core, config, request, broker, error);
            }
        } else {
            self.ended_sources.remove(&source);
        }
    }

    fn fail(
        &mut self,
        core: &mut Core,
        config: &Config,
        broker: &UnixDatagram,
        error: &mut String,
        reason: &str,
    ) {
        core.coalesce_pending_reports();
        self.connection = None;
        self.pending = None;
        self.queue.clear();
        self.last_error = reason.into();
        self.scheduled.clear();
        self.schedule_context = None;
        self.ended_sources.clear();
        self.injection_sources.clear();
        self.last_ack = None;
        self.next_tick = None;
        self.allowed_sources.clear();
        core.counters.delegate_errors += 1;
        core.delegate_pending = false;
        core.delegate_context = false;
        core.pressed_matrix
            .retain(|_, a| !matches!(a, Action::Delegated(_)));
        for id in self.owned_injections.drain() {
            if let Ok(reports) = core.apply_injected_key_event_with_route(
                &id,
                "KC_NONE",
                false,
                InjectedRoute::Normal,
            ) {
                for report in reports {
                    emit_report(broker, config, core, &report, error);
                }
            }
        }
        for (layer, source) in self.owned_layers.drain() {
            core.apply_layer_action(
                LayerAction {
                    op: LayerOp::Momentary,
                    layer,
                },
                false,
                source,
            );
        }
    }

    fn commit(&mut self, core: &mut Core, ack: &Value) -> Result<Vec<RoutedReport>, String> {
        if self.last_ack.as_ref() == Some(ack) {
            return Ok(Vec::new());
        }
        let Some((request, _)) = self.pending.as_ref() else {
            return Err("unexpected_delegate_ack".into());
        };
        for field in [
            "protocol",
            "event_id",
            "owner_epoch",
            "keymap_revision",
            "layer_revision",
        ] {
            if ack.get(field) != request.get(field) {
                return Err(format!("delegate_{field}_mismatch"));
            }
        }
        if ack["t"] != "delegate_ack" || ack["result"].as_str().is_some_and(|value| value != "ok") {
            return Err("delegate_rejected".into());
        }
        if request["keymap_revision"].as_u64() != Some(core.keymap_revision) {
            return Err("delegate_generation_stale".into());
        }
        let operations = ack["layer_ops"]
            .as_array()
            .ok_or("delegate_layer_ops_required")?;
        let keys = ack["key_events"]
            .as_array()
            .ok_or("delegate_key_events_required")?;
        if operations.len() > 256 || keys.len() > 1024 || !ack["context_active"].is_boolean() {
            return Err("delegate_invalid_ack".into());
        }
        let next_tick = match ack.get("next_tick_ms") {
            Some(Value::Null) | None => None,
            Some(value) => Some(Duration::from_secs_f64(
                value
                    .as_f64()
                    .filter(|v| v.is_finite() && *v >= 0.0 && *v < 1e12)
                    .ok_or("delegate_invalid_timer")?
                    / 1000.0,
            )),
        };
        let mut layers = Vec::new();
        let mut layer_owners = self.owned_layers.clone();
        for operation in operations {
            let source = operation["source"]
                .as_u64()
                .or_else(|| operation["source"].as_str().and_then(|v| v.parse().ok()))
                .ok_or("delegate_invalid_source")?;
            if !self.allowed_sources.contains(&source) && !self.ended_sources.contains(&source) {
                return Err("delegate_source_not_authorized".into());
            }
            if self.ended_sources.contains(&source) {
                continue;
            }
            let op = operation["op"]
                .as_str()
                .ok_or("delegate_invalid_layer_op")?;
            if op == "clear_locks" {
                layers.push(LayerChange::Lock(None, false));
                continue;
            }
            if op == "lock" {
                let layer = operation["layer"]
                    .as_u64()
                    .filter(|v| *v < core.layers.len() as u64)
                    .ok_or("delegate_invalid_layer")? as usize;
                let press = operation["is_press"]
                    .as_bool()
                    .ok_or("delegate_invalid_press")?;
                layers.push(LayerChange::Lock(Some(layer), press));
                continue;
            }
            if op == "consume_oneshot" {
                layers.push(LayerChange::Consume);
                continue;
            }
            let op = match op {
                "mo" => LayerOp::Momentary,
                "tg" => LayerOp::Toggle,
                "to" => LayerOp::To,
                "df" => LayerOp::Default,
                "osl" => LayerOp::OneShot,
                _ => return Err("delegate_invalid_layer_op".into()),
            };
            let layer = operation["layer"]
                .as_u64()
                .filter(|layer| *layer < 256)
                .ok_or("delegate_invalid_layer")? as usize;
            let source = operation["source"]
                .as_u64()
                .or_else(|| operation["source"].as_str().and_then(|v| v.parse().ok()))
                .ok_or("delegate_invalid_source")?;
            let row = operation["row"]
                .as_u64()
                .filter(|v| *v <= 15)
                .ok_or("delegate_invalid_coordinate")? as u8;
            let col = operation["col"]
                .as_u64()
                .filter(|v| *v <= 15)
                .ok_or("delegate_invalid_coordinate")? as u8;
            let press = operation["is_press"]
                .as_bool()
                .ok_or("delegate_invalid_press")?;
            if layer >= core.layers.len()
                && !(op == LayerOp::Momentary
                    && !press
                    && layer_owners.contains(&(layer, (source, row, col))))
            {
                return Err("delegate_invalid_layer".into());
            }
            if op == LayerOp::Momentary {
                let identity = (source, row, col);
                if press {
                    if !matches!(
                        core.pressed_matrix.get(&identity),
                        Some(Action::Delegated(_))
                    ) {
                        return Err("delegate_layer_owner_mismatch".into());
                    }
                    layer_owners.insert((layer, identity));
                } else if !layer_owners.remove(&(layer, identity)) {
                    return Err("delegate_layer_owner_mismatch".into());
                }
            }
            layers.push(LayerChange::Apply(
                LayerAction { op, layer },
                press,
                (source, row, col),
            ));
        }
        let mut events = Vec::new();
        let mut injection_owners = self.injection_sources.clone();
        let mut total_delay = 0u64;
        for key in keys {
            let id = key["id"]
                .as_str()
                .filter(|id| !id.is_empty() && id.len() <= 512)
                .ok_or("delegate_invalid_key_id")?;
            let action = key["action"]
                .as_str()
                .ok_or("delegate_invalid_key_action")?;
            let press = key["is_press"]
                .as_bool()
                .ok_or("delegate_invalid_key_press")?;
            if press && !matches!(core.action_from_str(action), Action::Key(_)) {
                return Err("delegate_nonkeyboard_key_event".into());
            }
            let route = injected_route_from_request(key["route"].as_str())?;
            let source = key["source"]
                .as_u64()
                .or_else(|| key["source"].as_str().and_then(|v| v.parse().ok()))
                .ok_or("delegate_invalid_key_source")?;
            if !self.allowed_sources.contains(&source) && !self.ended_sources.contains(&source) {
                return Err("delegate_source_not_authorized".into());
            }
            let owned_id = format!("delegate:{id}");
            if injection_owners
                .get(&owned_id)
                .is_some_and(|owner| *owner != source)
            {
                return Err("delegate_injection_owner_mismatch".into());
            }
            if press {
                injection_owners.insert(owned_id, source);
            } else {
                injection_owners.remove(&owned_id);
            }
            let delay = key
                .get("delay_before_ms")
                .map(|v| v.as_u64().filter(|v| *v <= 1000))
                .unwrap_or(Some(0))
                .ok_or("delegate_invalid_delay")?;
            total_delay += delay;
            if total_delay > 2000 {
                return Err("delegate_schedule_too_long".into());
            }
            events.push((
                total_delay,
                format!("delegate:{id}"),
                action.to_owned(),
                press,
                route,
                source,
            ));
        }
        for change in layers {
            match change {
                LayerChange::Apply(layer, press, identity) => {
                    core.apply_layer_action(layer, press, identity);
                    if layer.op == LayerOp::Momentary {
                        if press {
                            self.owned_layers.insert((layer.layer, identity));
                        } else {
                            self.owned_layers.remove(&(layer.layer, identity));
                        }
                    }
                }
                LayerChange::Consume => core.clear_oneshot_layers(),
                LayerChange::Lock(layer, press) => {
                    let before = core.layer_snapshot();
                    if let Some(layer) = layer {
                        if press {
                            core.locked_layers.insert(layer);
                            core.oneshot_layers.remove(&layer);
                        } else {
                            core.locked_layers.remove(&layer);
                        }
                    } else {
                        core.locked_layers.clear();
                    }
                    if before != core.layer_snapshot() {
                        core.layer_revision += 1;
                    }
                }
            }
        }
        let now = Instant::now();
        for (delay, id, action, press, route, source) in events {
            if !self.ended_sources.contains(&source) {
                self.scheduled.push_back((
                    now + Duration::from_millis(delay),
                    id,
                    action,
                    press,
                    route,
                    source,
                ));
            }
        }
        self.schedule_context = ack["context_active"].as_bool();
        if request["t"] == "delegate_source_end" {
            if let Some(source) = request["source"].as_u64() {
                self.ended_sources.remove(&source);
            }
        }
        self.last_ack = Some(ack.clone());
        self.next_tick = next_tick;
        self.pending = None;
        self.last_error = ack["companion_error"]
            .as_str()
            .unwrap_or("")
            .chars()
            .take(128)
            .collect();
        Ok(Vec::new())
    }

    pub(super) fn poll(
        &mut self,
        core: &mut Core,
        config: &Config,
        broker: &UnixDatagram,
        error: &mut String,
    ) {
        let mut failed = None;
        let mut lines = Vec::new();
        if let Some(client) = self.connection.as_mut() {
            if flush_pending(&mut client.stream, &mut client.output).is_err() {
                failed = Some("delegate_write_failed");
            }
            let mut buf = [0; 8192];
            for _ in 0..16 {
                match client.stream.read(&mut buf) {
                    Ok(0) => {
                        failed = Some("delegate_eof");
                        break;
                    }
                    Ok(n) => {
                        client.input.extend_from_slice(&buf[..n]);
                        if client.input.len() > MAX_LINE {
                            failed = Some("delegate_line_too_large");
                            break;
                        }
                    }
                    Err(err) if err.kind() == ErrorKind::WouldBlock => break,
                    Err(_) => {
                        failed = Some("delegate_read_failed");
                        break;
                    }
                }
            }
            while let Some(end) = client.input.iter().position(|byte| *byte == b'\n') {
                lines.push(client.input.drain(..=end).collect::<Vec<_>>());
            }
        }
        if let Some(reason) = failed {
            self.fail(core, config, broker, error, reason);
            return;
        }
        for line in lines {
            let ack = match serde_json::from_slice::<Value>(&line) {
                Ok(ack) => ack,
                Err(_) => {
                    self.fail(core, config, broker, error, "delegate_invalid_json");
                    return;
                }
            };
            match self.commit(core, &ack) {
                Ok(reports) => {
                    for report in reports {
                        emit_report(broker, config, core, &report, error);
                    }
                }
                Err(reason) => {
                    self.fail(core, config, broker, error, &reason);
                    return;
                }
            }
        }
        if self
            .pending
            .as_ref()
            .is_some_and(|(_, started)| started.elapsed() > ACK_DEADLINE)
        {
            self.fail(core, config, broker, error, "delegate_ack_timeout");
            return;
        }
        while self
            .scheduled
            .front()
            .is_some_and(|(due, _, _, _, _, _)| *due <= Instant::now())
        {
            let (due, id, action, press, route, source) = self.scheduled.pop_front().unwrap();
            match core.apply_injected_key_event_with_route(&id, &action, press, route) {
                Ok(reports) => {
                    for report in reports {
                        emit_report(broker, config, core, &report, error);
                    }
                }
                Err(_) => {
                    self.fail(core, config, broker, error, "delegate_output_rejected");
                    return;
                }
            }
            if press {
                self.owned_injections.insert(id.clone());
                self.injection_sources.insert(id, source);
            } else {
                self.owned_injections.remove(&id);
                self.injection_sources.remove(&id);
            }
            // Preserve host-facing gaps from the actual preceding send. An
            // already-late first press must not shorten its following hold.
            shift_following_deadlines(&mut self.scheduled, due, Instant::now());
        }
        if self.scheduled.is_empty() && self.pending.is_none() {
            core.delegate_pending = false;
            if let Some(active) = self.schedule_context.take() {
                core.delegate_context = active;
            }
        }
        while self.pending.is_none() && self.scheduled.is_empty() {
            let Some(work) = self.queue.pop_front() else {
                break;
            };
            match work {
                Work::Event(source, event) => {
                    self.execute_event(core, config, source, event, broker, error)
                }
                Work::End(source) => {
                    let mut request = self.envelope(core, "delegate_source_end");
                    request["source"] = json!(source);
                    self.send(core, config, request, broker, error);
                }
            }
        }
        if self.pending.is_none()
            && self.scheduled.is_empty()
            && core.delegate_context
            && self
                .next_tick
                .is_some_and(|due| self.started.elapsed() >= due)
        {
            self.next_tick = None;
            let request = self.envelope(core, "delegate_tick");
            self.send(core, config, request, broker, error);
        }
    }
}

fn shift_following_deadlines(
    schedule: &mut VecDeque<(Instant, String, String, bool, InjectedRoute, u64)>,
    due: Instant,
    sent: Instant,
) {
    let lateness = sent.saturating_duration_since(due);
    for (next, _, _, _, _, _) in schedule {
        *next += lateness;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn late_press_retains_the_full_sixty_ms_hold_and_twenty_ms_step_gap() {
        let due = Instant::now();
        let mut schedule = VecDeque::from([
            (
                due + Duration::from_millis(60),
                "tap".into(),
                "KC_A".into(),
                false,
                InjectedRoute::Normal,
                1,
            ),
            (
                due + Duration::from_millis(80),
                "next".into(),
                "KC_B".into(),
                true,
                InjectedRoute::Normal,
                1,
            ),
        ]);
        let sent = due + Duration::from_millis(17);
        shift_following_deadlines(&mut schedule, due, sent);
        assert_eq!(schedule[0].0 - sent, Duration::from_millis(60));
        assert_eq!(schedule[1].0 - schedule[0].0, Duration::from_millis(20));
        let release_due = schedule.pop_front().unwrap().0;
        let release_sent = release_due + Duration::from_millis(13);
        shift_following_deadlines(&mut schedule, release_due, release_sent);
        assert_eq!(schedule[0].0 - release_sent, Duration::from_millis(20));
    }
}
