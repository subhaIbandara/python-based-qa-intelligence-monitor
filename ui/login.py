"""Login page — the first screen. Credentials are validated against PostgreSQL."""
import tkinter as tk

from db import auth, repository
from ui import theme as T
from ui.widgets import FlatButton, run_async


class LoginFrame(tk.Frame):
    def __init__(self, parent, on_success):
        super().__init__(parent, bg=T.BG)
        self.on_success = on_success

        card = tk.Frame(self, bg=T.CARD, highlightbackground=T.BORDER, highlightthickness=1)
        card.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(card, text="◆", font=(T.FAMILY, 30), fg=T.ACCENT, bg=T.CARD).grid(
            row=0, column=0, columnspan=2, pady=(28, 0))
        tk.Label(card, text="QA Automation Intelligence", font=T.F_TITLE, fg=T.TEXT, bg=T.CARD).grid(
            row=1, column=0, columnspan=2, padx=40)
        tk.Label(card, text="Sign in to the quality dashboard", font=T.F_BODY, fg=T.MUTED, bg=T.CARD).grid(
            row=2, column=0, columnspan=2, pady=(2, 22))

        tk.Label(card, text="Username", font=T.F_BODY, fg=T.MUTED, bg=T.CARD).grid(
            row=3, column=0, sticky="w", padx=(40, 10), pady=6)
        self.username = tk.Entry(card, width=26, font=T.F_BODY, bg=T.CARD_HI, fg=T.TEXT, insertbackground=T.TEXT,
                                 relief="flat", highlightthickness=1, highlightbackground=T.BORDER,
                                 highlightcolor=T.ACCENT)
        self.username.grid(row=3, column=1, padx=(0, 40), pady=6, ipady=6)

        tk.Label(card, text="Password", font=T.F_BODY, fg=T.MUTED, bg=T.CARD).grid(
            row=4, column=0, sticky="w", padx=(40, 10), pady=6)
        self.password = tk.Entry(card, width=26, show="*", font=T.F_BODY, bg=T.CARD_HI, fg=T.TEXT,
                                 insertbackground=T.TEXT, relief="flat", highlightthickness=1,
                                 highlightbackground=T.BORDER, highlightcolor=T.ACCENT)
        self.password.grid(row=4, column=1, padx=(0, 40), pady=6, ipady=6)

        self.error = tk.Label(card, text="", font=T.F_SMALL, fg=T.BAD, bg=T.CARD, wraplength=320)
        self.error.grid(row=5, column=0, columnspan=2, pady=(6, 0))

        self.button = FlatButton(card, "Login", self.submit, padx=24)
        self.button.grid(row=6, column=0, columnspan=2, pady=(10, 18), sticky="ew", padx=40)

        self.status = tk.Label(card, text="Checking database…", font=T.F_SMALL, fg=T.MUTED, bg=T.CARD,
                               wraplength=360, justify="center")
        self.status.grid(row=7, column=0, columnspan=2, pady=(0, 22), padx=20)

        self.username.bind("<Return>", lambda e: self.password.focus_set())
        self.password.bind("<Return>", lambda e: self.submit())
        self.after(100, self.username.focus_set)
        run_async(self, self._check_db, self._show_db_status)

    @staticmethod
    def _check_db():
        ok, msg = repository.check_connection()
        hint = ""
        if ok and auth.user_count() == 0:
            hint = "\nNo users yet — create one:  python manage_users.py add <username>"
        return ok, msg, hint

    def _show_db_status(self, value, error):
        ok, msg, hint = value if value else (False, str(error).splitlines()[0], "")
        text = f"● Connected · {msg}{hint}" if ok else f"● Database unavailable · {msg}"
        self.status.configure(text=text, fg=T.GOOD if ok and not hint else (T.WARN if ok else T.BAD))

    def submit(self):
        if not self.button.enabled:
            return
        user, pw = self.username.get(), self.password.get()
        self.button.set_enabled(False, "Signing in…")
        self.error.configure(text="")
        run_async(self, lambda: auth.authenticate(user, pw), lambda v, e: self._done(v, e, user))

    def _done(self, value, error, user):
        ok, msg = value if value else (False, f"Database error: {str(error).splitlines()[0]}")
        self.button.set_enabled(True, "Login")
        if ok:
            self.password.delete(0, "end")
            self.on_success(user, msg)
        else:
            self.error.configure(text=msg)
            self.password.delete(0, "end")
            self.password.focus_set()

    def reset(self):
        self.error.configure(text="")
        self.password.delete(0, "end")
        self.username.focus_set()
