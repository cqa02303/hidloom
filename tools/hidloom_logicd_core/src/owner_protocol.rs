//! Executing-owner guards and connection-owned synthetic input. No device I/O here.
use super::*;

pub(super) struct GuardedTap {
    operation_id: String,
    injection_id: String,
    action: String,
    deadline: Instant,
}

pub(super) fn output_ready(config: &Config) -> bool {
    if !config.output_enabled {
        return false;
    }
    let Ok(meta) = fs::metadata(&config.output_status_path) else {
        return false;
    };
    if meta
        .modified()
        .ok()
        .and_then(|time| time.elapsed().ok())
        .is_none_or(|age| age > Duration::from_secs(3))
    {
        return false;
    }
    let Ok(bytes) = fs::read(&config.output_status_path) else {
        return false;
    };
    let Ok(state) = serde_json::from_slice::<Value>(&bytes) else {
        return false;
    };
    state["process"] == true
        && state["target"] == "auto"
        && state["last_error"].as_str() == Some("")
        && state["readiness"]["pending_usb_neutral"] == false
        && ((state["effective_target"] == "usb" && state["readiness"]["usb"] == "ready")
            || (state["effective_target"] == "uinput" && state["readiness"]["uinput"] == true))
}

impl Core {
    pub(super) fn end_guarded_tap(&mut self, reason: &str) -> Vec<RoutedReport> {
        let Some(tap) = self.guarded_tap.take() else {
            return Vec::new();
        };
        self.coalesce_pending_reports();
        let reports = self
            .apply_injected_key_event_with_route(
                &tap.injection_id,
                &tap.action,
                false,
                InjectedRoute::Normal,
            )
            .unwrap_or_default();
        if let Some((_, _, result)) = self
            .keymap_operations
            .iter_mut()
            .find(|(id, _, _)| *id == tap.operation_id)
        {
            result["state"] = json!("released");
            result["release_reason"] = json!(reason);
        }
        reports
    }

    pub(super) fn guarded_deadline_due(&self, now: Instant) -> bool {
        self.guarded_tap
            .as_ref()
            .is_some_and(|tap| now >= tap.deadline)
    }

    pub(super) fn start_guarded_tap(
        &mut self,
        request: &Value,
        ready: bool,
        now: Instant,
    ) -> (Value, Vec<RoutedReport>) {
        let fail = |error: &str| {
            (
                json!({"result":"error", "state":"rejected", "error":error}),
                Vec::new(),
            )
        };
        let Some(id) = request["operation_id"]
            .as_str()
            .filter(|id| !id.is_empty() && id.len() <= 128)
        else {
            return fail("operation_id_required");
        };
        if let Some((_, previous, result)) =
            self.keymap_operations.iter().find(|(old, _, _)| old == id)
        {
            return if previous == request {
                (result.clone(), Vec::new())
            } else {
                fail("operation_id_conflict")
            };
        }
        if request["expected_owner_epoch"].as_str() != Some(self.owner_epoch.as_str()) {
            return fail("owner_epoch_mismatch");
        }
        if request["expected_keymap_revision"].as_u64() != Some(self.keymap_revision) {
            return fail("keymap_revision_mismatch");
        }
        if request["expected_layer_revision"].as_u64() != Some(self.layer_revision) {
            return fail("layer_revision_mismatch");
        }
        if request["expected_output_revision"].as_u64() != Some(self.output_revision) {
            return fail("output_revision_mismatch");
        }
        let (Some(row), Some(col)) = (
            request["row"].as_u64().filter(|v| *v <= 15),
            request["col"].as_u64().filter(|v| *v <= 15),
        ) else {
            return fail("invalid_coordinate");
        };
        let Some(hold) = request["hold_ms"]
            .as_u64()
            .filter(|v| (5..=200).contains(v))
        else {
            return fail("invalid_hold_ms");
        };
        let action = self.resolve_action_string(row as u8, col as u8).to_owned();
        if request["expected_action"].as_str() != Some(action.as_str()) {
            return fail("action_mismatch");
        }
        let name = action.strip_prefix("KC_").unwrap_or("");
        if !(name == "ESC"
            || (name.len() == 1
                && name.as_bytes()[0].is_ascii_alphanumeric()
                && !name.as_bytes()[0].is_ascii_lowercase()))
        {
            return fail("action_not_allowlisted");
        }
        if !matches!(
            self.action_from_str(&action),
            Action::Key(KeyAction {
                code: 4..=41,
                reserved: 0
            })
        ) {
            return fail("action_not_allowlisted");
        }
        if self.owner_state(None, None)["idle"] != true {
            return fail("owner_not_idle");
        }
        if !ready {
            return fail("output_not_ready");
        }
        let injection_id = format!("guard:{id}");
        let reports = match self.apply_injected_key_event_with_route(
            &injection_id,
            &action,
            true,
            InjectedRoute::Normal,
        ) {
            Ok(reports) => reports,
            Err(error) => return fail(&error),
        };
        self.guarded_tap = Some(GuardedTap {
            operation_id: id.into(),
            injection_id,
            action,
            deadline: now + Duration::from_millis(hold),
        });
        let result = json!({"result":"ok", "state":"started", "operation_id":id, "owner_epoch":self.owner_epoch,
            "keymap_revision":self.keymap_revision, "layer_revision":self.layer_revision, "output_revision":self.output_revision,
            "delivery":"owner_accepted", "hold_ms":hold});
        if self.keymap_operations.len() == 128 {
            self.keymap_operations.pop_front();
        }
        self.keymap_operations
            .push_back((id.into(), request.clone(), result.clone()));
        (result, reports)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> Core {
        Core::new(
            HashMap::from([("KC_A".into(), 4), ("KC_B".into(), 5)]),
            vec![HashMap::from([("0,0".into(), "KC_A".into())])],
            RoutingConfig::default(),
        )
    }
    fn request(core: &Core) -> Value {
        json!({"t":"guarded_tap", "operation_id":"tap-1", "expected_owner_epoch":core.owner_epoch,
        "expected_keymap_revision":core.keymap_revision, "expected_layer_revision":core.layer_revision,
        "expected_output_revision":core.output_revision, "row":0,"col":0,"expected_action":"KC_A","hold_ms":30})
    }
    #[test]
    fn guarded_positive_duplicate_and_deadline_are_owner_owned() {
        let mut core = fixture();
        let request = request(&core);
        let now = Instant::now();
        let (result, reports) = core.start_guarded_tap(&request, true, now);
        assert_eq!(result["state"], "started");
        assert_eq!(reports.len(), 1);
        assert_eq!(core.start_guarded_tap(&request, true, now).1.len(), 0);
        assert!(!core.guarded_deadline_due(now));
        assert!(core.guarded_deadline_due(now + Duration::from_millis(30)));
        assert_eq!(core.end_guarded_tap("deadline")[0].report, [0; 8]);
        assert_eq!(
            core.start_guarded_tap(&request, true, now).0["state"],
            "released"
        );
        assert_eq!(core.hid.build(), [0; 8]);
    }
    #[test]
    fn stale_guard_held_modifier_and_invalid_action_emit_nothing() {
        let mut core = fixture();
        let mut req = request(&core);
        req["expected_layer_revision"] = json!(0);
        assert!(
            core.start_guarded_tap(&req, true, Instant::now())
                .1
                .is_empty()
        );
        req = request(&core);
        core.apply_injected_key_event_with_route("other", "KC_B", true, InjectedRoute::Normal)
            .unwrap();
        assert_eq!(
            core.start_guarded_tap(&req, true, Instant::now()).0["error"],
            "owner_not_idle"
        );
        assert_eq!(core.hid.build()[2], 5);
    }
    #[test]
    fn source_release_preserves_same_position_other_action_and_mo_ownership() {
        let mut core = fixture();
        core.apply_source_event(
            1,
            MatrixEvent {
                press: true,
                row: 0,
                col: 0,
            },
        );
        core.layers[0].insert("0,0".into(), "KC_B".into());
        core.apply_source_event(
            2,
            MatrixEvent {
                press: true,
                row: 0,
                col: 0,
            },
        );
        assert_eq!(&core.hid.build()[2..4], &[4, 5]);
        core.apply_source_event(
            1,
            MatrixEvent {
                press: false,
                row: 0,
                col: 0,
            },
        );
        assert!(!core.hid.build().contains(&4));
        assert!(core.hid.build().contains(&5));
        core.apply_source_event(
            2,
            MatrixEvent {
                press: false,
                row: 0,
                col: 0,
            },
        );
        assert_eq!(core.hid.build(), [0; 8]);
    }
}
