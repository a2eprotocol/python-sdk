from a2e.caps.proc.client import ProcsAPI


def on_event(event):
    print(f"[event] {event.type} | data={getattr(event, 'data', None)}")


def run_proc(client):
    # ─────────────────────────────────────────────
    # Example: Process (via API)
    # ─────────────────────────────────────────────
    procs = ProcsAPI(client)
    resp = procs.spawn(
        cmd=["python3", "-u", "-c", "print(input())"],
        on_output=on_event
    )

    if not resp.ok:
        print("Spawn failed:", resp.error)
        return

    proc_id = resp.proc_id

    # Send input
    procs.write(proc_id, "hello world\n", eof=True)

    while True:
        try:
            resp = procs.status(proc_id)
        except Exception as e:
            print("Status error:", e)
            break

        if not resp:
            print("Process not found (possibly cleaned up)")
            break

        state = resp.status
        returncode = resp.error

        print(f"[STATUS] state={state}, returncode={returncode}")

        if state in ("completed", "killed", "failed"):
            print("Process finished")
            break

    resp = procs.kill(proc_id)
    resp = procs.status(proc_id)

    state = resp.status
    if state == 'killed':
        print("proc killed")

    return
