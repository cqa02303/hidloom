# ledd Direct Frame Fallback

更新日: 2026-05-30

`ledd` の direct-frame producer が `/tmp/ledd_direct_frame.sock` から切断した時の fallback policy を記録する。

## 背景

`tools/demo/play_led_video.py --backend ledd-direct` は、1 frame = 1 `LDF1` packet で `ledd` へ直接 LED frame を送る。
producer が終了・クラッシュ・切断した後、`ledd` が何を表示し続けるかを明示する必要がある。

## 方針

既定運用は `restore_default` とする。

理由:

- `KC_SH2` の 2 回目押下で動画再生を停止し、通常 animation へ戻せる
- producer が終了・クラッシュした時も動画の最後の frame が残らない
- direct-frame 動画再生を一時的な override として扱える

## policy

| policy | 挙動 |
|---|---|
| `keep_last_frame` | 最後に受け取った frame を維持する |
| `off` | producer 切断時に全 LED を消灯する |
| `restore_default` | producer 切断時に default animation へ戻す |

## 設定

`config/default/ledd.json` の `ipc.direct_frame_fallback` で指定する。

```json
{
  "ipc": {
    "direct_frame_socket_path": "/tmp/ledd_direct_frame.sock",
    "direct_frame_fallback": "restore_default"
  }
}
```

環境変数でも上書きできる。

```bash
LEDD_DIRECT_FRAME_FALLBACK=off PYTHONPATH=daemon python3 -m ledd.ledd
```

## 実装メモ

- `direct_frame_receiver()` は producer connect / disconnect を stats に記録する
- `direct_frame_receiver()` は `on_producer_disconnected` callback を呼ぶ
- `AnimationManager.on_direct_frame_producer_disconnected()` が fallback policy を適用する
- `restore_default` は direct-frame lock の外で `switch(default_id)` を呼ぶ

## テスト

```bash
python3 script/test_ledd_direct_frame_fallback.py
```

確認内容:

- `keep_last_frame` では direct-frame active と last frame id を維持する
- `off` では LED を消灯し direct-frame state を解除する
- `restore_default` では default animation へ戻す
- `LEDD_DIRECT_FRAME_FALLBACK` が config より優先される

## 実機確認

2026-05-22 に `<keyboard-host>` で、systemd drop-in による一時上書きで確認した。

| policy | 実機結果 |
|---|---|
| `keep_last_frame` | producer 切断後も `direct_frame_active=true` のまま最後の frame を維持 |
| `off` | producer 切断後に `direct_frame_active=false`、`last_applied_frame_id=null` になり消灯 |
| `restore_default` | producer 切断後に `direct_frame_active=false` になり、default animation `ripple` へ復帰 |

10 秒 / 24fps の `tools/demo/play_led_video.py --backend ledd-direct` 実測では、`played frames=240 fps=23.9`、
`accepted_frames=240`、`applied_frames=240`、`ignored_frames=0`、`rejected_frames=0` を確認した。
Python/OpenCV 起動と動画初期化込みの wall clock は約 26.18 秒、子プロセス CPU は約 39.5% だった。

## 関連

- [direct-frame-socket-plan.md](direct-frame-socket-plan.md)
- [daemon/ledd/README.md](../../../../daemon/ledd/README.md)
- [demo/README.md](../../../../demo/README.md)
