"""Main window: login → dashboard (stacked frames switched with tkraise)."""
import csv
import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from config import BASE_DIR, QA_BASE_URL, TARGET_HOST
from data import source
from db.repository import PROJECTS
from engine.analytics import QAAnalytics
from ui import theme as T
from ui.login import LoginFrame
from engine.suite import SuiteAnalytics
from ui.pages import (DashboardPage, EnvironmentsPage, InsightsPage, MethodologyPage, RiskPage, SignalsPage,
                      TestAnalyticsPage, TimeframesPage)
from ui.widgets import FlatButton, run_async

POLL_MS = 15_000
NAV = [("Overview", DashboardPage), ("Test Analytics", TestAnalyticsPage), ("Quality Trends", SignalsPage),
       ("Risk", RiskPage),
       ("Timeframes", TimeframesPage), ("Environments & APIs", EnvironmentsPage),
       ("Insights", InsightsPage), ("Methodology", MethodologyPage)]
PROJECT_MODE = {"live": "run", "demo": "day"}
PROJECT_SOURCE = {"live": f"Site under test: {QA_BASE_URL}", "demo": "Generated 90-day history (no real site)"}


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("QA Automation Intelligence")
        root.geometry("1440x920")
        root.minsize(1100, 700)
        T.apply(root)

        container = tk.Frame(root, bg=T.BG)
        container.pack(fill="both", expand=True)
        self.login = LoginFrame(container, self.on_login)
        self.main = MainFrame(container, self)
        for frame in (self.login, self.main):
            frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.login.tkraise()

    def on_login(self, username, display_name):
        self.main.start(username, display_name)
        self.main.tkraise()

    def logout(self):
        self.main.stop()
        self.root.config(menu=tk.Menu(self.root))
        self.login.reset()
        self.login.tkraise()


class MainFrame(tk.Frame):
    def __init__(self, parent, app: App):
        super().__init__(parent, bg=T.BG)
        self.app = app
        self.analytics = None
        self.project = "live"
        self.marker = None
        self.poll_job = None
        self.loading = False
        self.test_proc = None

        side = tk.Frame(self, bg=T.PANEL, width=230)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Label(side, text="◆ QA Intelligence", font=(T.FAMILY, 15, "bold"), fg=T.TEXT, bg=T.PANEL).pack(
            anchor="w", padx=18, pady=(20, 2))
        self.user_lbl = tk.Label(side, text="", font=T.F_SMALL, fg=T.MUTED, bg=T.PANEL)
        self.user_lbl.pack(anchor="w", padx=18)

        tk.Label(side, text="PROJECT", font=(T.FAMILY, 9, "bold"), fg=T.MUTED, bg=T.PANEL).pack(
            anchor="w", padx=18, pady=(18, 4))
        self.project_cb = ttk.Combobox(side, values=list(PROJECTS.values()), state="readonly", width=22)
        self.project_cb.set(PROJECTS[self.project])
        self.project_cb.pack(padx=18, anchor="w")
        self.project_cb.bind("<<ComboboxSelected>>", self._project_changed)
        self.source_lbl = tk.Label(side, text=PROJECT_SOURCE[self.project], font=T.F_SMALL, fg=T.MUTED,
                                   bg=T.PANEL, wraplength=195, justify="left")
        self.source_lbl.pack(anchor="w", padx=18, pady=(6, 0))

        tk.Label(side, text="VIEWS", font=(T.FAMILY, 9, "bold"), fg=T.MUTED, bg=T.PANEL).pack(
            anchor="w", padx=18, pady=(18, 4))
        self.nav_items = {}
        for name, _ in NAV:
            lbl = tk.Label(side, text=name, font=T.F_BODY, fg=T.MUTED, bg=T.PANEL, anchor="w", padx=18, pady=7,
                           cursor="hand2")
            lbl.pack(fill="x")
            lbl.bind("<Button-1>", lambda e, n=name: self.show(n))
            self.nav_items[name] = lbl

        bottom = tk.Frame(side, bg=T.PANEL)
        bottom.pack(side="bottom", fill="x", padx=18, pady=18)
        self.run_btn = FlatButton(bottom, "▶  Run tests", self.run_tests, bg=T.GOOD, fg="#ffffff")
        self.run_btn.pack(fill="x")
        FlatButton(bottom, "⟳  Refresh", self.refresh, bg=T.CARD_HI).pack(fill="x", pady=(8, 0))
        FlatButton(bottom, "Logout", self.app.logout, bg=T.PANEL, fg=T.MUTED).pack(fill="x", pady=(8, 0))
        self.status = tk.Label(bottom, text="", font=T.F_SMALL, fg=T.MUTED, bg=T.PANEL, wraplength=195,
                               justify="left")
        self.status.pack(fill="x", pady=(12, 0))

        self.content = tk.Frame(self, bg=T.BG)
        self.content.pack(side="right", fill="both", expand=True)
        self.pages = {}
        for name, cls in NAV:
            page = cls(self.content)
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.pages[name] = page
        self.empty = EmptyState(self.content, self)
        self.empty.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.current = "Overview"

    # ---------------------------------------------------------------- lifecycle
    def start(self, username, display_name):
        self.user_lbl.configure(text=f"Signed in as {display_name}")
        self._menu()
        self.show("Overview")
        self.refresh()
        self._schedule_poll()

    def stop(self):
        if self.poll_job:
            self.after_cancel(self.poll_job)
            self.poll_job = None
        self.analytics = None

    def _menu(self):
        bar = tk.Menu(self.app.root)
        file_menu = tk.Menu(bar, tearoff=0)
        file_menu.add_command(label="Refresh", command=self.refresh)
        file_menu.add_command(label="Run Playwright tests", command=self.run_tests)
        file_menu.add_command(label="Export insights (CSV)…", command=self.export_insights)
        file_menu.add_separator()
        file_menu.add_command(label="Regenerate demo data…", command=self.reseed)
        file_menu.add_separator()
        file_menu.add_command(label="Logout", command=self.app.logout)
        file_menu.add_command(label="Exit", command=self.app.root.quit)
        bar.add_cascade(label="File", menu=file_menu)
        view = tk.Menu(bar, tearoff=0)
        for name, _ in NAV:
            view.add_command(label=name, command=lambda n=name: self.show(n))
        bar.add_cascade(label="View", menu=view)
        self.app.root.config(menu=bar)

    # --------------------------------------------------------------- navigation
    def show(self, name):
        self.current = name
        for n, lbl in self.nav_items.items():
            lbl.configure(bg=T.CARD_HI if n == name else T.PANEL, fg=T.TEXT if n == name else T.MUTED)
        if self.analytics is None:
            self.empty.tkraise()
        else:
            self.pages[name].tkraise()

    def _project_changed(self, _event=None):
        key = [k for k, v in PROJECTS.items() if v == self.project_cb.get()][0]
        if key != self.project:
            self._set_project(key)
            self.refresh()

    def _set_project(self, key):
        self.project = key
        self.project_cb.set(PROJECTS[key])
        self.source_lbl.configure(text=PROJECT_SOURCE[key])

    # ------------------------------------------------------------------- data
    def refresh(self):
        if self.loading:
            return
        self.loading = True
        project = self.project
        self.status.configure(text=f"Loading {PROJECTS[project]}…", fg=T.MUTED)

        def work():
            data, msg = source.load(project)
            analytics = QAAnalytics(data, PROJECT_MODE[project]) if data is not None else None
            if analytics is not None:      # heavy pandas work stays off the UI thread
                analytics.suite = SuiteAnalytics(analytics, 28 if project == "demo" else 10)
            return analytics, msg, source.latest_marker(project)

        def done(value, error):
            if error is not None:
                self._failed(error)
            else:
                self._loaded(project, *value)

        run_async(self, work, done)

    def _loaded(self, project, analytics, msg, marker):
        self.loading = False
        if project != self.project:          # switched while loading
            return self.refresh()
        self.analytics, self.marker = analytics, marker
        stamp = datetime.now().strftime("%H:%M:%S")
        if analytics is None:
            self.empty.set(msg)
            self.status.configure(text=f"{msg}\nUpdated {stamp}", fg=T.WARN)
        else:
            target = QA_BASE_URL if project == "live" else PROJECTS[project]
            meta = f"{target} · {analytics.kpis['runs']} runs · refreshed {stamp}"
            for page in self.pages.values():
                page.update(analytics, meta)
            self.status.configure(text=f"{msg}\nUpdated {stamp} · auto-refresh on", fg=T.MUTED)
        self.show(self.current)

    def _failed(self, err):
        self.loading = False
        self.status.configure(text=f"Load failed: {str(err).splitlines()[0]}", fg=T.BAD)
        messagebox.showerror("Load failed", str(err))

    def _schedule_poll(self):
        self.poll_job = self.after(POLL_MS, self._poll)

    def _poll(self):
        project = self.project
        # a transient DB error keeps the old marker, so we simply try again next tick
        run_async(self, lambda: source.latest_marker(project),
                  lambda marker, err: self._poll_result(project, self.marker if err else marker))

    def _poll_result(self, project, marker):
        if self.poll_job is None:
            return
        if project == self.project and marker != self.marker and not self.loading:
            self.refresh()
        self._schedule_poll()

    # ------------------------------------------------------------------ actions
    def run_tests(self):
        if self.test_proc is not None:
            messagebox.showinfo("Tests running", "A test run is already in progress.")
            return
        win = tk.Toplevel(self)
        win.title(f"Playwright test run — {TARGET_HOST}")
        win.geometry("860x480")
        win.configure(bg=T.BG)
        text = tk.Text(win, bg=T.CARD, fg=T.TEXT, font=T.F_MONO, relief="flat", insertbackground=T.TEXT)
        text.pack(fill="both", expand=True, padx=10, pady=10)
        lines = queue.Queue()
        cmd = [sys.executable, "-m", "pytest", "tests/e2e", "-v", "--tb=line", "-p", "no:cacheprovider"]
        text.insert("end", f"Site under test: {QA_BASE_URL}\n$ " + " ".join(cmd[2:]) + "\n\n")
        self.run_btn.set_enabled(False, "Running…")
        self.test_proc = subprocess.Popen(cmd, cwd=BASE_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                          text=True, bufsize=1)

        def reader(proc):
            for line in proc.stdout:
                lines.put(line)
            lines.put(None)

        threading.Thread(target=reader, args=(self.test_proc,), daemon=True).start()

        def pump():
            try:
                while True:
                    line = lines.get_nowait()
                    if line is None:
                        code = self.test_proc.wait()
                        self.test_proc = None
                        self.run_btn.set_enabled(True, "▶  Run tests")
                        text.insert("end", f"\nExit code {code} — results recorded; dashboard refreshing.\n")
                        text.see("end")
                        if self.project != "live":
                            self._set_project("live")
                        self.refresh()
                        return
                    if text.winfo_exists():
                        text.insert("end", line)
                        text.see("end")
            except queue.Empty:
                pass
            self.after(100, pump)

        pump()

    def reseed(self):
        if not messagebox.askyesno("Regenerate demo data",
                                   "Replace the synthetic demo project with freshly generated history?\n"
                                   "Live test results are not affected."):
            return
        try:
            source.reseed_demo(seed=int(datetime.now().timestamp()) % 10_000)
        except Exception as err:  # noqa: BLE001
            messagebox.showerror("Failed", str(err))
            return
        if self.project == "demo":
            self.refresh()

    def export_insights(self):
        if self.analytics is None:
            messagebox.showwarning("Nothing to export", "No data loaded.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="qa_insights.csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["severity", "area", "title", "evidence", "recommendation"])
            for i in self.analytics.insights:
                writer.writerow([i.severity, i.area, i.title, i.evidence, i.recommendation])
        messagebox.showinfo("Exported", f"{len(self.analytics.insights)} insights written to\n{path}")


class EmptyState(tk.Frame):
    def __init__(self, parent, main: MainFrame):
        super().__init__(parent, bg=T.BG)
        box = tk.Frame(self, bg=T.BG)
        box.place(relx=0.5, rely=0.45, anchor="center")
        tk.Label(box, text="No data yet", font=T.F_TITLE, fg=T.TEXT, bg=T.BG).pack()
        self.msg = tk.Label(box, text="", font=T.F_BODY, fg=T.MUTED, bg=T.BG, wraplength=520)
        self.msg.pack(pady=10)
        FlatButton(box, "▶  Run Playwright tests now", main.run_tests, bg=T.GOOD).pack(pady=6)

    def set(self, msg):
        self.msg.configure(text=msg)
