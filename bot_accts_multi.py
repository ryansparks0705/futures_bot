"""
futures_multi_acct_gui_vSwing_v2.py
 • One Tk window = config + override + kill
 • Any time after hitting Start you can:
      ▸ press  UP / DOWN  to force swing direction
      ▸ press  KILL BOT  to exit immediately
 • Heart‑beat prints every 1 s
"""

from ib_insync import *
from datetime import datetime
from calendar import monthcalendar, FRIDAY
from threading import Thread
import tkinter as tk, tkinter.messagebox as mb, pytz, os, sys, time

# ───────── editable defaults ────────────────────────────────────────
ACCOUNTS_AVAILABLE = ["DU12345", "DU67890", "DU8030486"]
DEFAULT_EXEC_TIME  = "12:39:55"
TP_LONG = 5;  SL_LONG = 7.5
TP_SHORT = 5; SL_SHORT = 5
# ────────────────────────────────────────────────────────────────────

CONFIG          = {}        # filled after “Start”
OVERRIDE_RESULT = None       # gui‑set to "UP"/"DOWN"
KILL_FLAG       = False

# ══ helpers ═════════════════════════════════════════════════════════
def second_friday(y, m):
    cal = monthcalendar(y, m)
    return cal[1][FRIDAY] if cal[0][FRIDAY] else cal[2][FRIDAY]

def front_month(sym):
    t = datetime.today(); y, m = t.year, t.month
    qm = ((m - 1) // 3 + 1) * 3
    if t.day > second_friday(y, qm):
        qm += 3; y += qm // 13; qm = ((qm - 1) % 12) + 1
    return f"{y}{qm:02d}"

# ══ GUI (single window) ═════════════════════════════════════════════
def build_gui():
    root = tk.Tk(); root.title("Futures Swing‑Bot")

    # ── mode & exec time ────────────────────────────────────────────
    mode_var = tk.StringVar(value="PAPER")
    tk.Label(root, text="Mode").grid(row=0, column=0, sticky="e")
    tk.Radiobutton(root, text="Paper", variable=mode_var,
                   value="PAPER").grid(row=0, column=1, sticky="w")
    tk.Radiobutton(root, text="Live",  variable=mode_var,
                   value="LIVE").grid(row=0, column=2, sticky="w")

    tk.Label(root, text="Exec HH:MM:SS").grid(row=1, column=0, sticky="e")
    exec_var = tk.StringVar(value=DEFAULT_EXEC_TIME)
    tk.Entry(root, textvariable=exec_var, width=10)\
        .grid(row=1, column=1, sticky="w")

    # ── account table ───────────────────────────────────────────────
    tk.Label(root, text="Accounts").grid(row=2, column=0, sticky="ne")
    frame = tk.Frame(root); frame.grid(row=2, column=1, columnspan=3, sticky="w")

    acct_vars = {}
    for acc in ACCOUNTS_AVAILABLE:
        chk  = tk.BooleanVar()
        sym  = tk.StringVar(value="MES")
        qty  = tk.IntVar(value=0)
        swg  = tk.DoubleVar(value=5.0)
        row  = tk.Frame(frame)
        tk.Checkbutton(row, text=acc, variable=chk, width=10).pack(side="left")
        tk.Entry(row, textvariable=sym, width=6).pack(side="left")
        tk.Spinbox(row, from_=0, to=999, width=5,
                   textvariable=qty).pack(side="left")
        tk.Spinbox(row, from_=0, to=50, increment=0.5, width=5,
                   textvariable=swg).pack(side="left")
        row.pack(anchor="w", pady=1)
        acct_vars[acc] = (chk, sym, qty, swg)

    # ── override & kill buttons ─────────────────────────────────────
    over_frame = tk.Frame(root); over_frame.grid(row=3, column=0,
                                                 columnspan=4, pady=6)
    tk.Button(over_frame, text="UP", width=10,
              command=lambda: set_override("UP")).pack(side="left", padx=5)
    tk.Button(over_frame, text="DOWN", width=10,
              command=lambda: set_override("DOWN")).pack(side="left", padx=5)
    tk.Button(over_frame, text="KILL BOT", width=12, bg="#f33", fg="white",
              command=kill_bot).pack(side="left", padx=15)

    # ── start button ────────────────────────────────────────────────
    def start():
        try:
            hh, mm, ss = map(int, exec_var.get().split(":"))
        except ValueError:
            mb.showerror("Input error", "Exec time HH:MM:SS"); return

        sel = {}
        for acc, (chk, sym, qty, swg) in acct_vars.items():
            if chk.get() and qty.get() > 0 and swg.get() > 0:
                sel[acc] = dict(symbol=sym.get().strip().upper(),
                                qty=qty.get(), swing=float(swg.get()))
        if not sel:
            mb.showerror("Input error", "Need ≥1 account with qty>0"); return

        CONFIG.update(mode=mode_var.get(),
                      exec=(hh, mm, ss),
                      accounts=sel)
        start_btn.config(state="disabled")
        Thread(target=trading_thread, daemon=True).start()

    start_btn = tk.Button(root, text="Start Bot", width=20, command=start)
    start_btn.grid(row=4, column=0, columnspan=4, pady=8)

    root.mainloop()

def set_override(d):
    global OVERRIDE_RESULT
    OVERRIDE_RESULT = d
    print(f">>> OVERRIDE set to {d}")

def kill_bot():
    global KILL_FLAG
    KILL_FLAG = True
    print(">>> KILL signal sent – bot will exit shortly")

# ══ swing‑tracking & trading logic ══════════════════════════════════
def track_swings(ib, md_map, exec_time):
    tz = pytz.timezone("US/Central")
    target = datetime.now(tz).replace(hour=exec_time[0],
                                      minute=exec_time[1],
                                      second=exec_time[2], microsecond=0)

    st = {}
    for k, md in md_map.items():
        while md.last is None or md.last != md.last:
            ib.sleep(0.05)
        p = md.last
        st[k] = dict(lo=p, hi=p, dir=None, price=p)

    print("Tracking swings…")
    last_ping = time.time()
    while datetime.now(tz) < target and not KILL_FLAG:
        ib.sleep(0.25)

        for (sym, swing), md in md_map.items():
            p = md.last or st[(sym, swing)]['price']
            lo = st[(sym, swing)]['lo']
            hi = st[(sym, swing)]['hi']
            latest = st[(sym, swing)]['dir']

            if p - lo >= swing:               # swing up
                print(f"{sym} ↑{swing} {lo}->{p}")
                latest = "UP"; lo = hi = p
            elif p - hi <= -swing:            # swing down
                print(f"{sym} ↓{swing} {hi}->{p}")
                latest = "DOWN"; lo = hi = p

            st[(sym, swing)].update(
                lo=min(lo, p), hi=max(hi, p), dir=latest, price=p)

        # 1‑sec heartbeat
        if time.time() - last_ping >= 1:
            for (sym, swing), s in st.items():
                print(f"[{datetime.now(tz):%H:%M:%S}] {sym} "
                      f"p={s['price']} lo={s['lo']} hi={s['hi']} "
                      f"swing={swing} dir={s['dir']}")
            last_ping = time.time()

    dir_map   = {k: v['dir']   for k, v in st.items()}
    price_map = {k: v['price'] for k, v in st.items()}
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

# ══ background thread that runs the bot ═════════════════════════════
def trading_thread():
    print("Config →", CONFIG)
    ib = IB()
    port = 7497 if CONFIG["mode"] == "PAPER" else 7496
    ib.connect("127.0.0.1", port, clientId=1)

    valid = set(ib.managedAccounts())
    CONFIG["accounts"] = {a: cfg for a, cfg in CONFIG["accounts"].items()
                          if a in valid}
    if not CONFIG["accounts"]:
        print("No valid accounts – abort"); return

    combos = {(cfg['symbol'], cfg['swing'])
              for cfg in CONFIG["accounts"].values()}
    md_map = {}
    for sym, sw in combos:
        fut = Future(symbol=sym,
                     lastTradeDateOrContractMonth=front_month(sym),
                     exchange="CME", currency="USD")
        ib.qualifyContracts(fut)
        md_map[(sym, sw)] = ib.reqMktData(fut, "", False, False)

    dir_map, price_map = track_swings(ib, md_map, CONFIG["exec"])
    if OVERRIDE_RESULT:
        dir_map = {k: OVERRIDE_RESULT for k in dir_map}

    if KILL_FLAG:
        print("Bot killed before order placement"); ib.disconnect(); return

    pid = ib.client.getReqId()
    for acct, cfg in CONFIG["accounts"].items():
        sym, qty, sw = cfg['symbol'], cfg['qty'], cfg['swing']
        direction = dir_map.get((sym, sw))
        if direction not in ("UP", "DOWN"):
            print(f"{acct}: no swing for {sym}@{sw} – skip"); continue

        side = "BUY" if direction == "UP" else "SELL"
        tp, sl = (TP_LONG, SL_LONG) if side == "BUY" else (TP_SHORT, SL_SHORT)
        entry  = price_map[(sym, sw)]

        fut = Future(symbol=sym,
                     lastTradeDateOrContractMonth=front_month(sym),
                     exchange="CME", currency="USD")
        ib.qualifyContracts(fut)

        print(f"{acct}: {side} {qty} {sym} @ {entry} (swing={sw})")
        for o in bracket(pid, side, qty, entry, tp, sl):
            o.account = acct
            ib.placeOrder(fut, o); ib.sleep(0.25)
        pid += 3

    print("All orders sent.")
    ib.disconnect()

# ══ run ═════════════════════════════════════════════════════════════
if __name__ == "__main__":
    build_gui()
