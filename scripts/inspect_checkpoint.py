# -*- coding: utf-8 -*-
"""快速查看 checkpoints.db 里存了什么（用 msgpack 解 BLOB）"""
import sqlite3
import json
import sys
import os

try:
    import msgpack
except ImportError:
    print("先装一下: pip install msgpack")
    sys.exit(1)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "checkpoints.db")


def _decode_obj(obj):
    """把 msgpack 里的 Python 对象（带 langchain 类名）转成可读 dict"""
    if isinstance(obj, dict):
        cls = obj.get("lc", obj.get("__class__", None))
        if cls is not None:
            data = obj.get("data", obj)
            result = {"__type__": obj.get("name", cls) if isinstance(cls, int) else str(cls)}
            if isinstance(data, dict):
                for k, v in data.items():
                    result[k] = _decode_obj(v)
            else:
                result["_raw"] = str(data)[:300]
            return result
        return {k: _decode_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decode_obj(v) for v in obj]
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except Exception:
            return f"<bytes:{len(obj)}>"
    return obj


def main():
    if not os.path.exists(DB_PATH):
        print(f"数据库不存在: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT thread_id, checkpoint_id FROM checkpoints ORDER BY rowid DESC LIMIT 1")
    latest = cur.fetchone()
    if not latest:
        print("checkpoints 表是空的")
        conn.close()
        return

    print(f"=== 最新 checkpoint (thread_id={latest['thread_id']}) ===\n")

    cur.execute(
        "SELECT checkpoint, metadata FROM checkpoints WHERE thread_id=? AND checkpoint_id=?",
        (latest["thread_id"], latest["checkpoint_id"]),
    )
    row = cur.fetchone()

    # 1. metadata (JSON)
    meta = json.loads(row["metadata"]) if row["metadata"] else {}
    print(f"[metadata] {json.dumps(meta, indent=2, ensure_ascii=False)}\n")

    # 2. checkpoint (msgpack)
    ckpt = msgpack.unpackb(row["checkpoint"], raw=False)
    print(f"[checkpoint keys] {list(ckpt.keys())}\n")

    for key, val in ckpt.items():
        if key == "channel_values":
            print("--- channel_values（图 state 内容）---")
            decoded = _decode_obj(val)
            for ch_key, ch_val in decoded.items():
                print(f"\n  [{ch_key}]:")
                text = json.dumps(ch_val, indent=2, ensure_ascii=False, default=str)
                # 限制长度
                if len(text) > 2000:
                    text = text[:2000] + "\n  ...(截断)"
                for line in text.split("\n"):
                    print(f"    {line}")
        elif key == "channel_versions":
            print(f"\n--- channel_versions ---")
            print(f"  {json.dumps(_decode_obj(val), indent=2, ensure_ascii=False)}")
        else:
            print(f"\n--- {key} ---")
            decoded = _decode_obj(val)
            s = json.dumps(decoded, indent=2, ensure_ascii=False, default=str)
            print(s[:2000])

    conn.close()


if __name__ == "__main__":
    main()