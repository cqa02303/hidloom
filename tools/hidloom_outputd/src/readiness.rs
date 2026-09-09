use std::fs;
use std::io::Read;
use std::os::unix::net::UnixDatagram;
use std::path::Path;
use std::time::{Duration, SystemTime};

use serde_json::Value;

// hidd and uidd publish at least once per 500 ms when idle. Three publication
// periods allow scheduling jitter while rejecting stopped producers promptly.
pub const POLL_INTERVAL: Duration = Duration::from_millis(500);
pub const STATUS_MAX_AGE: Duration = Duration::from_millis(1500);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum UsbReadiness {
    Ready,
    Detached,
    Unknown,
}

#[derive(Debug)]
pub struct Sample {
    pub usb: UsbReadiness,
    pub uinput: bool,
    pub reason: &'static str,
}

#[derive(Clone, Default)]
pub struct Paths {
    pub gadget_udc: String,
    pub udc_root: String,
    pub hidd_status: String,
    pub uidd_status: String,
}

fn status(path: &str, now: SystemTime) -> Option<Value> {
    let file = fs::File::open(path).ok()?;
    let metadata = file.metadata().ok()?;
    if metadata.len() > 65536
        || now.duration_since(metadata.modified().ok()?).ok()? > STATUS_MAX_AGE
    {
        return None;
    }
    let mut data = String::new();
    file.take(65537).read_to_string(&mut data).ok()?;
    if data.len() > 65536 {
        return None;
    }
    serde_json::from_str(&data).ok()
}

fn live_socket(value: &Value, path: &str) -> bool {
    value["process"].as_bool() == Some(true)
        && value["socket"]["listening"].as_bool() == Some(true)
        && value["socket"]["path"].as_str() == Some(path)
        && UnixDatagram::unbound()
            .and_then(|socket| socket.connect(path))
            .is_ok()
}

pub fn sample(paths: &Paths, usb_socket: &str, uidd_socket: &str, now: SystemTime) -> Sample {
    let uinput = status(&paths.uidd_status, now).is_some_and(|value| {
        value["schema"].as_str() == Some("hidloom.uidd.status.v1")
            && live_socket(&value, uidd_socket)
            && value["dry_run"].as_bool() == Some(false)
            && value["uinput"]["open"].as_bool() == Some(true)
    });
    let unknown = |reason| Sample {
        usb: UsbReadiness::Unknown,
        uinput,
        reason,
    };
    let Ok(bound) = fs::read_to_string(&paths.gadget_udc) else {
        return unknown("gadget_udc_unreadable");
    };
    let bound = bound.trim();
    // An unbound/missing gadget is not evidence that a formerly attached host
    // released its keys. Only the bound controller's physical detach qualifies.
    if bound.is_empty() || bound.contains('/') || bound == "." || bound == ".." {
        return unknown("gadget_udc_invalid");
    }
    let Ok(state) = fs::read_to_string(Path::new(&paths.udc_root).join(bound).join("state")) else {
        return unknown("bound_udc_unreadable");
    };
    if state.trim() == "not attached" {
        return Sample {
            usb: UsbReadiness::Detached,
            uinput,
            reason: "usb_detached",
        };
    }
    if state.trim() != "configured" {
        return unknown("usb_enumerating_or_suspended");
    }
    let Some(value) = status(&paths.hidd_status, now) else {
        return unknown("hidd_status_stale_or_invalid");
    };
    if value["schema"].as_str() != Some("hidd.status.v1")
        || !live_socket(&value, usb_socket)
        || value["endpoints"]["hidg0"]["open"].as_bool() != Some(true)
        || value["endpoints"]["hidg2"]["open"].as_bool() != Some(true)
    {
        return unknown("hidd_not_ready");
    }
    Sample {
        usb: UsbReadiness::Ready,
        uinput,
        reason: "usb_ready",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::UNIX_EPOCH;

    #[test]
    fn wrong_udc_stale_malformed_and_socket_only_are_not_ready() {
        let root = std::env::temp_dir().join(format!(
            "output-readiness-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(root.join("udc/owned")).unwrap();
        fs::create_dir_all(root.join("udc/unrelated")).unwrap();
        fs::write(root.join("UDC"), "owned").unwrap();
        fs::write(root.join("udc/owned/state"), "configured").unwrap();
        fs::write(root.join("udc/unrelated/state"), "configured").unwrap();
        let usb = root.join("usb.sock");
        let uidd = root.join("ui.sock");
        let _usb = UnixDatagram::bind(&usb).unwrap();
        let _uidd = UnixDatagram::bind(&uidd).unwrap();
        let paths = Paths {
            gadget_udc: root.join("UDC").to_string_lossy().into_owned(),
            udc_root: root.join("udc").to_string_lossy().into_owned(),
            hidd_status: root.join("hidd.json").to_string_lossy().into_owned(),
            uidd_status: root.join("uidd.json").to_string_lossy().into_owned(),
        };
        let usb = usb.to_str().unwrap();
        let uidd = uidd.to_str().unwrap();
        assert_eq!(
            sample(&paths, usb, uidd, SystemTime::now()).usb,
            UsbReadiness::Unknown
        );
        fs::write(&paths.hidd_status, serde_json::json!({"schema":"hidd.status.v1", "process":true,
            "socket":{"listening":true,"path":usb},"endpoints":{"hidg0":{"open":true},"hidg2":{"open":true}}}).to_string()).unwrap();
        fs::write(
            &paths.uidd_status,
            serde_json::json!({"schema":"hidloom.uidd.status.v1", "process":true,
            "socket":{"listening":true,"path":uidd},"dry_run":false,"uinput":{"open":true}})
            .to_string(),
        )
        .unwrap();
        let now = SystemTime::now();
        let ready = sample(&paths, usb, uidd, now);
        assert_eq!(ready.usb, UsbReadiness::Ready);
        assert!(ready.uinput);
        let stale = sample(&paths, usb, uidd, now + STATUS_MAX_AGE + POLL_INTERVAL);
        assert_eq!(stale.usb, UsbReadiness::Unknown);
        assert!(!stale.uinput);
        fs::write(root.join("UDC"), "missing").unwrap();
        assert_eq!(
            sample(&paths, usb, uidd, SystemTime::now()).usb,
            UsbReadiness::Unknown
        );
        fs::write(root.join("UDC"), "owned").unwrap();
        fs::write(&paths.hidd_status, "{ malformed \"open\":true }").unwrap();
        assert_eq!(
            sample(&paths, usb, uidd, SystemTime::now()).usb,
            UsbReadiness::Unknown
        );
        fs::write(root.join("udc/owned/state"), "suspended").unwrap();
        assert_eq!(
            sample(&paths, usb, uidd, SystemTime::now()).usb,
            UsbReadiness::Unknown
        );
        fs::write(root.join("udc/owned/state"), "not attached").unwrap();
        assert_eq!(
            sample(&paths, usb, uidd, SystemTime::now()).usb,
            UsbReadiness::Detached
        );
        fs::remove_dir_all(root).unwrap();
    }
}
