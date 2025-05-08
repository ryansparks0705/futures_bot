"""
futures_multi_acct_gui_vSwing.py
 • GUI ① main config  • GUI ② override / cancel
 • Each account: Symbol · Qty · Swing‑pts
 • Independent bracket per account
 • FIX 2024‑05‑xx: swing message now prints old‑extreme → new price
"""

from ib_insync import *
from datetime import datetime
from calendar import monthcalendar, FRIDAY
from threading import Thread
import tkinter as tk, pytz, os, sys

# ────────── editable lists ───────────────────────────────────────────
ACCOUNTS_AVAILABLE = ["DU12345", "DU67890", "DU8030486"]
DEFAULT_EXEC_TIME  = "12:39:55"
TP_LONG = 5;  SL_LONG = 7.5
TP_SHORT = 5; SL_SHORT = 5
# ─────────────────────────────────────────────────────────────────────

CONFIG          = {}       # filled by GUI
OVERRIDE_RESULT = None

# ══ GUI ① main configuration ════════════════════════════════════════
def config_gui():
    def launch():
        try:
            hh, mm, ss = map(int, exec_var.get().split(":"))
        except ValueError:
            tk.messagebox.showerror("Input error", "Exec time HH:MM:SS")
            return

        sel = {}
        for acc, (chk, sym, qty, swg) in acct_vars.items():
            if chk.get() and qty.get() > 0 and swg.get() > 0:
                sel[acc] = dict(symbol=sym.get().strip().upper(),
                                qty=qty.get(),
                                swing=float(swg.get()))
        if not sel:
            tk.messagebox.showerror("Input error", "Need ≥1 account with qty>0")
            return

        CONFIG.update(mode=mode_var.get(),
                      exec=(hh, mm, ss),
                      accounts=sel)
        root.destroy()

    root = tk.Tk()
    root.title("Futures – Config")

    mode_var = tk.StringVar(value="PAPER")
    tk.Label(root, text="Mode:").grid(row=0, column=0, sticky="e")
    tk.Radiobutton(root, text="Paper", variable=mode_var, value="PAPER")\
        .grid(row=0, column=1, sticky="w")
    tk.Radiobutton(root, text="Live", variable=mode_var, value="LIVE")\
        .grid(row=0, column=2, sticky="w")

    tk.Label(root, text="Exec HH:MM:SS").grid(row=1, column=0, sticky="e")
    exec_var = tk.StringVar(value=DEFAULT_EXEC_TIME)
    tk.Entry(root, textvariable=exec_var, width=10)\
        .grid(row=1, column=1, sticky="w")

    tk.Label(root, text="Accounts").grid(row=2, column=0, sticky="ne")
    frame = tk.Frame(root); frame.grid(row=2, column=1, columnspan=3, sticky="w")

    acct_vars = {}
    for acc in ACCOUNTS_AVAILABLE:
        chk = tk.BooleanVar()
        sym = tk.StringVar(value="MES")
        qty = tk.IntVar(value=0)
        swg = tk.DoubleVar(value=5.0)
        row = tk.Frame(frame)
        tk.Checkbutton(row, text=acc, variable=chk, width=10).pack(side="left")
        tk.Entry(row, textvariable=sym, width=6).pack(side="left")
        tk.Spinbox(row, from_=0, to=999, width=5, textvariable=qty).pack(side="left")
        tk.Spinbox(row, from_=0, to=50, increment=0.5, width=5,
                   textvariable=swg).pack(side="left")
        row.pack(anchor="w", pady=1)
        acct_vars[acc] = (chk, sym, qty, swg)

    tk.Button(root, text="Launch", command=launch)\
        .grid(row=3, column=0, columnspan=4, pady=8)
    root.mainloop()

# ══ GUI ② override / cancel ═════════════════════════════════════════
def override_gui():
    def choose(d):
        global OVERRIDE_RESULT
        OVERRIDE_RESULT = d
        win.destroy()

    def cancel():
        print("Cancelled."); os._exit(0)

    win = tk.Tk(); win.title("Override")
    tk.Label(win, text="Override swing direction?").pack(padx=10, pady=8)
    tk.Button(win, text="UP",   width=10, command=lambda: choose("UP")).pack(pady=2)
    tk.Button(win, text="DOWN", width=10, command=lambda: choose("DOWN")).pack(pady=2)
    tk.Button(win, text="CANCEL", width=12, bg="#f33", fg="white",
              command=cancel).pack(pady=6)
    win.mainloop()

# ══ helpers ═════════════════════════════════════════════════════════
def second_friday(y, m):
    cal = monthcalendar(y, m)
    return cal[1][FRIDAY] if cal[0][FRIDAY] else cal[2][FRIDAY]

def front_month(sym):
    t = datetime.today(); y, m = t.year, t.month
    qm = ((m - 1) // 3 + 1) * 3          # 3‑6‑9‑12 cycle
    if t.day > second_friday(y, qm):
        qm += 3; y += qm // 13; qm = ((qm - 1) % 12) + 1
    return f"{y}{qm:02d}"

# ───────── swing tracking (FIXED printout) ──────────────────────────
def track_swings(ib, md_map, exec_time):
    tz = pytz.timezone("US/Central")
    target = datetime.now(tz).replace(hour=exec_time[0],
                                      minute=exec_time[1],
                                      second=exec_time[2],
                                      microsecond=0)

    state = {}  # (sym,swing) -> dict(lo,hi,dir,price)
    for key, md in md_map.items():
        while md.last is None or md.last != md.last:
            ib.sleep(0.1)
        p = md.last
        state[key] = dict(lo=p, hi=p, dir=None, price=p)

    print("Tracking swings…")
    last_ping = datetime.now()
    while datetime.now(tz) < target:
        ib.sleep(1)

        for key, md in md_map.items():
            sym, swing = key
            p = md.last or state[key]['price']
            lo, hi, latest = state[key]['lo'], state[key]['hi'], state[key]['dir']

            # ----- swing up --------------------------------------------------
            if p - lo >= swing:
                old_lo = lo                 # capture BEFORE reset  ❖❖ FIX ❖❖
                latest = "UP"
                print(f"{sym} ↑{swing} {old_lo}->{p}")
                lo = hi = p

            # ----- swing down ------------------------------------------------
            elif p - hi <= -swing:
                old_hi = hi
                latest = "DOWN"
                print(f"{sym} ↓{swing} {old_hi}->{p}")
                lo = hi = p

            lo = min(lo, p)
            hi = max(hi, p)
            state[key].update(lo=lo, hi=hi, dir=latest, price=p)

        # 5‑sec heartbeat
        now = datetime.now()
        if (now - last_ping).total_seconds() >= 5:
            for (sym, swing), s in state.items():
                print(f"[{now:%H:%M:%S}] {sym} "
                      f"p={s['price']} lo={s['lo']} hi={s['hi']} "
                      f"swing={swing} dir={s['dir']}")
            last_ping = now

    dir_map   = {k: v['dir']   for k, v in state.items()}
    price_map = {k: v['price'] for k, v in state.items()}
    return dir_map, price_map

def bracket(pid, side, qty, entry, tp, sl):
    p = Order(orderId=pid, action=side, orderType="MKT",
              totalQuantity=qty, transmit=False)
    t = Order(orderId=pid + 1,
              action="SELL" if side == "BUY" else "BUY",
              orderType="LMT",
              lmtPrice=entry + tp if side == "BUY" else entry - tp,
              totalQuantity=qty, parentId=pid, transmit=False)
    s = Order(orderId=pid + 2,
              action="SELL" if side == "BUY" else "BUY",
              orderType="STP",
              auxPrice=entry - sl if side == "BUY" else entry + sl,
              totalQuantity=qty, parentId=pid, transmit=True)
    return [p, t, s]

# ══ main ════════════════════════════════════════════════════════════
def main():
    config_gui()
    print("Config →", CONFIG)

    ib = IB()
    port = 7497 if CONFIG["mode"] == "PAPER" else 7496
    ib.connect("127.0.0.1", port, clientId=1)

    # validate accounts
    valid = set(ib.managedAccounts())
    bad   = [a for a in CONFIG["accounts"] if a not in valid]
    if bad:
        print("Skip unknown accounts:", bad)
        CONFIG["accounts"] = {a: c for a, c in CONFIG["accounts"].items()
                              if a in valid}
    if not CONFIG["accounts"]:
        sys.exit("No valid accounts.")

    # one market‑data stream per (symbol, swing) combo
    combos = {(c['symbol'], c['swing']) for c in CONFIG["accounts"].values()}
    md_map = {}
    for sym, swing in combos:
        fut = Future(symbol=sym,
                     lastTradeDateOrContractMonth=front_month(sym),
                     exchange="CME", currency="USD")
        ib.qualifyContracts(fut)
        md_map[(sym, swing)] = ib.reqMktData(fut, "", False, False)

    Thread(target=override_gui, daemon=True).start()

    dir_map, price_map = track_swings(ib, md_map, CONFIG["exec"])
    if OVERRIDE_RESULT:
        dir_map = {k: OVERRIDE_RESULT for k in dir_map}

    pid = ib.client.getReqId()
    for acct, cfg in CONFIG["accounts"].items():
        sym, qty, sw = cfg['symbol'], cfg['qty'], cfg['swing']
        direction = dir_map.get((sym, sw))
        if direction not in ("UP", "DOWN"):
            print(f"{acct}: no swing for {sym}@{sw} – skip")
            continue

        side = "BUY" if direction == "UP" else "SELL"
        tp, sl = (TP_LONG, SL_LONG) if side == "BUY" else (TP_SHORT, SL_SHORT)
        entry = price_map[(sym, sw)]

        fut = Future(symbol=sym,
                     lastTradeDateOrContractMonth=front_month(sym),
                     exchange="CME", currency="USD")
        ib.qualifyContracts(fut)

        print(f"{acct}: {side} {qty} {sym} @ {entry} (swing={sw})")
        for o in bracket(pid, side, qty, entry, tp, sl):
            o.account = acct
            ib.placeOrder(fut, o)
            ib.sleep(.25)
        pid += 3

    print("All orders sent."); ib.disconnect()

if __name__ == "__main__":
    main()
