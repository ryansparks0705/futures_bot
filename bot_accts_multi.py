# futures_multi_acct_gui_vSwing.py  – 2024-05-xx  (fixed expiry logic)

from ib_insync import *
from datetime     import datetime, timedelta
from calendar     import monthcalendar, FRIDAY
from threading    import Thread
import tkinter as tk, tkinter.messagebox as mb
import pytz, asyncio, os, sys, time

# ───────── editable defaults ────────────────────────────────────────
ACCOUNTS_AVAILABLE = ["DU12345", "DU67890", "DU8030486"]
DEFAULT_EXEC_TIME  = "12:39:55"            # local (US/Central)

TP_LONG  = 5;  SL_LONG  = 7.5              # pts
TP_SHORT = 5;  SL_SHORT = 5
HEARTBEAT        = 1.0                     # seconds between prints
ROLL_DAYS_BEFORE = 0                       # ≥0: roll this many days *before*
# ────────────────────────────────────────────────────────────────────

CONFIG, OVERRIDE_RESULT = {}, None
KILL_FLAG = False

# ════════════════════════════════════════════════════════════════════
# helpers
# ════════════════════════════════════════════════════════════════════
def third_friday(y: int, m: int) -> datetime:
    """return a datetime for the 3rd Friday of <month>/<year>"""
    cal = monthcalendar(y, m)
    day = cal[2][FRIDAY] if cal[0][FRIDAY] else cal[3][FRIDAY]
    return datetime(y, m, day)

def front_month(sym: str) -> str:
    """
    Return the *current* quarterly expiry yyyymm string using 3rd-Friday logic.
    Rolls to next quarter AFTER (3rd Friday – ROLL_DAYS_BEFORE).
    """
    today = datetime.today()
    y, m  = today.year, today.month
    q_mon = ((m - 1)//3 + 1) * 3                     # 3-6-9-12

    roll_date = third_friday(y, q_mon) - timedelta(days=ROLL_DAYS_BEFORE)
    if today >= roll_date:                           # time to roll
        q_mon += 3
        if q_mon > 12:
            q_mon -= 12
            y += 1
    return f"{y}{q_mon:02d}"

def bracket(pid, side, qty, entry, tp, sl):
    parent = Order(orderId=pid, action=side, orderType="MKT",
                   totalQuantity=qty, transmit=False)
    tp_ord = Order(orderId=pid+1,
                   action="SELL" if side=="BUY" else "BUY",
                   orderType="LMT",
                   lmtPrice=entry+tp if side=="BUY" else entry-tp,
                   totalQuantity=qty, parentId=pid, transmit=False)
    sl_ord = Order(orderId=pid+2,
                   action="SELL" if side=="BUY" else "BUY",
                   orderType="STP",
                   auxPrice=entry-sl if side=="BUY" else entry+sl,
                   totalQuantity=qty, parentId=pid, transmit=True)
    return [parent, tp_ord, sl_ord]

# ════════════════════════════════════════════════════════════════════
# swing tracking
# ════════════════════════════════════════════════════════════════════
def track_swings(ib, md_map, exec_time):
    tz     = pytz.timezone("US/Central")
    target = datetime.now(tz).replace(hour=exec_time[0],
                                      minute=exec_time[1],
                                      second=exec_time[2],
                                      microsecond=0)

    state = {}                                  # (sym,swing)->dict
    for key, md in md_map.items():              # prime initial values
        while md.last is None or md.last != md.last:
            ib.sleep(.05)
        p = md.last
        state[key] = dict(lo=p, hi=p, dir=None, price=p)

    print("Tracking swings… start",
          ", ".join(f"{k[0]}@{k[1]}" for k in state))
    last_print = time.time()

    while datetime.now(tz) < target and not KILL_FLAG:
        ib.sleep(HEARTBEAT)

        for key, md in md_map.items():
            sym, swing = key
            p = md.last or state[key]['price']
            lo, hi, latest = state[key]['lo'], state[key]['hi'], state[key]['dir']

            if p - lo >= swing:
                print(f"{sym} ↑{swing} {lo}->{p}")
                latest, lo, hi = "UP", p, p
            elif p - hi <= -swing:
                print(f"{sym} ↓{swing} {hi}->{p}")
                latest, lo, hi = "DOWN", p, p

            state[key].update(price=p,
                              lo=min(lo, p),
                              hi=max(hi, p),
                              dir=latest)

        if time.time() - last_print >= HEARTBEAT:
            ts = datetime.now(tz).strftime("%H:%M:%S")
            for (sym, swing), s in state.items():
                print(f"[{ts}] {sym} "
                      f"p={s['price']} lo={s['lo']} hi={s['hi']} "
                      f"swing={swing} dir={s['dir']}")
            last_print = time.time()

    return ({k:v['dir']   for k,v in state.items()},
            {k:v['price'] for k,v in state.items()})

# ════════════════════════════════════════════════════════════════════
# unified GUI  –  config  ·  override  ·  kill
# ════════════════════════════════════════════════════════════════════
def build_gui():

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
            mb.showerror("Input error", "Select ≥1 account with qty>0"); return

        CONFIG.update(mode=mode_var.get(),
                      exec=(hh, mm, ss),
                      accounts=sel)
        start_btn.config(state="disabled")
        Thread(target=trading_thread, daemon=True).start()

    def override(direction):
        global OVERRIDE_RESULT
        OVERRIDE_RESULT = direction
        print(f"OVERRIDE → {direction}")

    def kill():
        global KILL_FLAG
        KILL_FLAG = True
        print("KILL signal sent – bot will exit shortly")
        root.after(800, root.destroy)

    # ── GUI layout
    root = tk.Tk(); root.title("Futures Swing-Bot")

    mode_var = tk.StringVar(value="PAPER")
    tk.Label(root, text="Mode").grid(row=0, column=0, sticky="e")
    tk.Radiobutton(root, text="Paper", variable=mode_var, value="PAPER")\
        .grid(row=0, column=1, sticky="w")
    tk.Radiobutton(root, text="Live",  variable=mode_var, value="LIVE")\
        .grid(row=0, column=2, sticky="w")

    tk.Label(root, text="Exec HH:MM:SS").grid(row=1, column=0, sticky="e")
    exec_var = tk.StringVar(value=DEFAULT_EXEC_TIME)
    tk.Entry(root, textvariable=exec_var, width=10)\
        .grid(row=1, column=1, sticky="w")

    tk.Label(root, text="Accounts").grid(row=2, column=0, sticky="ne")
    frame = tk.Frame(root); frame.grid(row=2, column=1, columnspan=3, sticky="w")

    acct_vars = {}
    for acc in ACCOUNTS_AVAILABLE:
        chk  = tk.BooleanVar()
        sym  = tk.StringVar(value="MES")
        qty  = tk.IntVar(value=0)
        swg  = tk.DoubleVar(value=5.0)
        row  = tk.Frame(frame)
        tk.Checkbutton(row, text=acc, variable=chk, width=11).pack(side="left")
        tk.Entry(row, textvariable=sym, width=6).pack(side="left")
        tk.Spinbox(row, from_=0, to=999, width=5, textvariable=qty).pack(side="left")
        tk.Spinbox(row, from_=0, to=50, increment=0.5, width=5,
                   textvariable=swg).pack(side="left")
        row.pack(anchor="w")
        acct_vars[acc] = (chk, sym, qty, swg)

    btn_row = tk.Frame(root); btn_row.grid(row=3, column=0, columnspan=4, pady=8)
    start_btn = tk.Button(btn_row, text="START BOT", width=12, command=start)
    start_btn.pack(side="left", padx=4)
    tk.Button(btn_row, text="UP",   width=6, command=lambda: override("UP"))\
        .pack(side="left")
    tk.Button(btn_row, text="DOWN", width=6, command=lambda: override("DOWN"))\
        .pack(side="left")
    tk.Button(btn_row, text="KILL", bg="#d22", fg="white",
              width=8, command=kill).pack(side="left", padx=4)

    root.mainloop()

# ════════════════════════════════════════════════════════════════════
# trading thread  (dedicated asyncio loop)
# ════════════════════════════════════════════════════════════════════
def trading_thread():
    asyncio.set_event_loop(asyncio.new_event_loop())     # ★ critical

    print("Config →", CONFIG)
    ib   = IB()
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
        print("No valid accounts – exiting."); return

    combos = {(c['symbol'], c['swing']) for c in CONFIG["accounts"].values()}
    md_map = {}
    for sym, swing in combos:
        fut = Future(symbol=sym,
                     lastTradeDateOrContractMonth=front_month(sym),
                     exchange="CME", currency="USD")
        ib.qualifyContracts(fut)
        md_map[(sym, swing)] = ib.reqMktData(fut, "", False, False)

    dir_map, price_map = track_swings(ib, md_map, CONFIG["exec"])
    if OVERRIDE_RESULT:
        dir_map = {k: OVERRIDE_RESULT for k in dir_map}

    pid = ib.client.getReqId()
    for acct, cfg in CONFIG["accounts"].items():
        if KILL_FLAG: break
        sym, qty, sw = cfg['symbol'], cfg['qty'], cfg['swing']
        direction    = dir_map.get((sym, sw))
        if direction not in ("UP", "DOWN"):
            print(f"{acct}: no swing for {sym}@{sw} – skip"); continue

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
            ib.placeOrder(fut, o); ib.sleep(.25)
        pid += 3

    print("All done."); ib.disconnect()

# ════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    build_gui()
