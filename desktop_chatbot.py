"""
Gemini Desktop Assistant - a chat window on your computer powered by the Gemini API.

Features: dark/light theme, formatted replies (bold, headings, bullet lists, code blocks),
"thinking" indicator, copy-last-reply, new chat, multi-turn memory, request timeout.

Setup:
    pip install google-genai
    export GEMINI_API_KEY="your-key"      (Windows: set GEMINI_API_KEY=your-key)
Run:
    python desktop_chatbot.py

tkinter ships with Python, so no UI library is needed.
Never hard-code or commit your API key.
"""

import os
import queue
import re
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from google import genai
from google.genai import types

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash")
SYSTEM = (
    "You are a helpful assistant for a computer science student. "
    "Answer clearly and concisely in simple language. "
    "Use short code examples when they help. If you are not sure, say so."
)

THEMES = {
    "light": dict(bg="#f4f5f9", panel="#ffffff", text="#1f2430", muted="#7a8194",
                  accent="#2f6fed", accent_fg="#ffffff", user_bg="#dce8ff",
                  bot_name="#1a8f5a", code_bg="#eceff5", error="#c62828",
                  border="#d5d9e4", btn="#e6e9f2"),
    "dark": dict(bg="#14161c", panel="#1c1f27", text="#e6e8ee", muted="#8a91a3",
                 accent="#4c8dff", accent_fg="#ffffff", user_bg="#25406f",
                 bot_name="#4cc38a", code_bg="#12141a", error="#ff6b6b",
                 border="#2c303b", btn="#2a2e3a"),
}

# bold **x**, inline code `x`, italic *x*
INLINE_RE = re.compile(r"(\*\*.+?\*\*|`[^`\n]+`|(?<![\*\w])\*[^\*\s][^\*\n]*?\*(?![\*\w]))")


def parse_inline(text: str):
    """Split a line into (text, tag) pieces; tag is None, 'bold', 'italic' or 'icode'."""
    parts, pos = [], 0
    for m in INLINE_RE.finditer(text):
        if m.start() > pos:
            parts.append((text[pos:m.start()], None))
        tok = m.group(0)
        if tok.startswith("**"):
            parts.append((tok[2:-2], "bold"))
        elif tok.startswith("`"):
            parts.append((tok[1:-1], "icode"))
        else:
            parts.append((tok[1:-1], "italic"))
        pos = m.end()
    if pos < len(text):
        parts.append((text[pos:], None))
    return parts


def pick_font(root, candidates, default):
    available = set(tkfont.families(root))
    for name in candidates:
        if name in available:
            return name
    return default


class ChatApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Gemini Desktop Assistant")
        root.geometry("780x660")
        root.minsize(520, 420)

        self.theme = "dark"
        self.ui = pick_font(root, ["Segoe UI", "Ubuntu", "Noto Sans", "DejaVu Sans", "Helvetica"],
                            "TkDefaultFont")
        self.mono = pick_font(root, ["Consolas", "Ubuntu Mono", "DejaVu Sans Mono", "Courier New"],
                              "TkFixedFont")

        # 30 s timeout so a bad network never leaves the window waiting forever
        self.client = genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(timeout=30000),
        )
        self.chat = self._new_chat()
        self.results = queue.Queue()  # worker thread -> UI thread
        self.busy = False
        self.dots = 0
        self.last_reply = ""
        self.buttons = []

        self._build_ui()
        self.apply_theme()
        self.add_message("bot", "Hi! Ask me anything. I can format **bold text**, lists and `code`.")
        self.poll()

    # ------------------------------------------------------------ UI construction
    def _make_button(self, parent, text, command, primary=False):
        b = tk.Button(parent, text=text, command=command, relief="flat", bd=0,
                      font=(self.ui, 10, "bold" if primary else "normal"),
                      padx=14, pady=6, cursor="hand2")
        self.buttons.append((b, primary))
        return b

    def _build_ui(self):
        self.header = tk.Frame(self.root)
        self.header.pack(fill=tk.X)
        self.title_lbl = tk.Label(self.header, text="Gemini Assistant",
                                  font=(self.ui, 14, "bold"))
        self.title_lbl.pack(side=tk.LEFT, padx=(16, 8), pady=12)
        self.status = tk.Label(self.header, text="Ready", font=(self.ui, 10))
        self.status.pack(side=tk.LEFT)

        self._make_button(self.header, "New chat", self.reset).pack(side=tk.RIGHT, padx=(6, 16), pady=10)
        self._make_button(self.header, "Copy reply", self.copy_last).pack(side=tk.RIGHT, padx=6, pady=10)
        self.theme_btn = self._make_button(self.header, "Light", self.toggle_theme)
        self.theme_btn.pack(side=tk.RIGHT, padx=6, pady=10)

        self.body = tk.Frame(self.root)
        self.body.pack(fill=tk.BOTH, expand=True)
        self.log = tk.Text(self.body, wrap=tk.WORD, state="disabled", relief="flat", bd=0,
                           padx=18, pady=12, font=(self.ui, 11), cursor="arrow",
                           highlightthickness=0)
        scroll = ttk.Scrollbar(self.body, command=self.log.yview)
        self.log.config(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.input_wrap = tk.Frame(self.root)
        self.input_wrap.pack(fill=tk.X)
        self.entry_box = tk.Frame(self.input_wrap, highlightthickness=1)
        self.entry_box.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(16, 8), pady=14)
        self.entry = tk.Entry(self.entry_box, relief="flat", bd=0, font=(self.ui, 12))
        self.entry.pack(fill=tk.X, padx=10, pady=9)
        self.entry.bind("<Return>", lambda e: self.send())
        self.entry.focus()
        self.send_btn = self._make_button(self.input_wrap, "Send", self.send, primary=True)
        self.send_btn.pack(side=tk.RIGHT, padx=(0, 16), pady=14)

    def _configure_tags(self, t):
        ui, mono, log = self.ui, self.mono, self.log
        log.tag_config("user_name", foreground=t["accent"], font=(ui, 10, "bold"), spacing1=6)
        log.tag_config("bot_name", foreground=t["bot_name"], font=(ui, 10, "bold"), spacing1=6)
        log.tag_config("error_name", foreground=t["error"], font=(ui, 10, "bold"), spacing1=6)
        log.tag_config("user", foreground=t["text"], background=t["user_bg"], font=(ui, 11),
                       spacing1=3, spacing3=3)
        log.tag_config("bot", foreground=t["text"], font=(ui, 11), spacing1=2, spacing3=2)
        log.tag_config("error", foreground=t["error"], font=(ui, 11))
        log.tag_config("bold", font=(ui, 11, "bold"))
        log.tag_config("italic", font=(ui, 11, "italic"))
        log.tag_config("icode", font=(mono, 10), background=t["code_bg"])
        log.tag_config("code", font=(mono, 10), background=t["code_bg"], lmargin1=10, lmargin2=10)
        log.tag_config("h1", font=(ui, 15, "bold"), spacing1=8)
        log.tag_config("h2", font=(ui, 13, "bold"), spacing1=6)
        log.tag_config("h3", font=(ui, 12, "bold"), spacing1=4)
        log.tag_config("muted", foreground=t["muted"])

    def apply_theme(self):
        t = THEMES[self.theme]
        self.root.configure(bg=t["bg"])
        for frame in (self.header, self.input_wrap):
            frame.configure(bg=t["bg"])
        self.title_lbl.configure(bg=t["bg"], fg=t["text"])
        self.status.configure(bg=t["bg"], fg=t["muted"])
        self.body.configure(bg=t["panel"])
        self.log.configure(bg=t["panel"], fg=t["text"], insertbackground=t["text"])
        self.entry_box.configure(bg=t["panel"], highlightbackground=t["border"],
                                 highlightcolor=t["accent"])
        self.entry.configure(bg=t["panel"], fg=t["text"], insertbackground=t["text"])
        for btn, primary in self.buttons:
            bg = t["accent"] if primary else t["btn"]
            fg = t["accent_fg"] if primary else t["text"]
            btn.configure(bg=bg, fg=fg, activebackground=bg, activeforeground=fg)
        self.theme_btn.configure(text="Light" if self.theme == "dark" else "Dark")
        self._configure_tags(t)

    def toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        self.apply_theme()

    # ------------------------------------------------------------ rendering
    def _newline(self, base):
        self.log.insert(tk.END, "\n", (base,))

    def _insert_inline(self, text, base, extra=()):
        for seg, tag in parse_inline(text):
            tags = (base,) + tuple(extra) + ((tag,) if tag else ())
            self.log.insert(tk.END, seg, tags)

    def render_markdown(self, text, base):
        in_code = False
        for raw in text.split("\n"):
            line = raw.rstrip()
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                self.log.insert(tk.END, " " + raw + " \n", (base, "code"))
                continue
            m = re.match(r"^(#{1,6})\s+(.*)$", line)
            if m:
                level = len(m.group(1))
                tag = "h1" if level == 1 else "h2" if level == 2 else "h3"
                self._insert_inline(m.group(2), base, (tag,))
                self._newline(base)
                continue
            if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", line.strip()):
                self.log.insert(tk.END, "\u2500" * 40 + "\n", (base, "muted"))
                continue
            m = re.match(r"^(\s*)[*\-]\s+(.*)$", line)
            if m:
                indent = "  " * (len(m.group(1)) // 2)
                self.log.insert(tk.END, indent + "\u2022  ", (base,))
                self._insert_inline(m.group(2), base)
                self._newline(base)
                continue
            self._insert_inline(line, base)
            self._newline(base)

    def add_message(self, who: str, text: str):
        label = {"user": "You", "bot": "Gemini", "error": "Error"}[who]
        self.log.config(state="normal")
        self.log.insert(tk.END, label + "\n", (who + "_name",))
        if who == "user":
            self.log.insert(tk.END, " " + text + " ", ("user",))
            self.log.insert(tk.END, "\n")
        elif who == "error":
            self.log.insert(tk.END, text + "\n", ("error",))
        else:
            self.render_markdown(text, "bot")
            self.last_reply = text
        self.log.insert(tk.END, "\n")
        self.log.config(state="disabled")
        self.log.see(tk.END)

    # ------------------------------------------------------------ chat logic
    def _new_chat(self):
        # A chat session keeps the conversation history, so follow-up questions work
        return self.client.chats.create(
            model=MODEL,
            config=types.GenerateContentConfig(system_instruction=SYSTEM, temperature=0.4),
        )

    def send(self):
        text = self.entry.get().strip()
        if not text or self.busy:
            return
        self.entry.delete(0, tk.END)
        self.add_message("user", text)
        self.set_busy(True)
        # API call runs in a background thread so the window never freezes
        threading.Thread(target=self.ask, args=(text,), daemon=True).start()

    def ask(self, text: str):
        # Background thread: must NOT touch the UI. It queues the result for poll().
        try:
            reply = self.chat.send_message(text).text or "(empty reply)"
            self.results.put((reply, "bot"))
        except Exception as e:
            print("API error:", repr(e))
            self.results.put((f"Request failed: {e}", "error"))

    def poll(self):
        try:
            while True:
                text, who = self.results.get_nowait()
                self.add_message(who, text)
                self.set_busy(False)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def set_busy(self, busy: bool):
        self.busy = busy
        self.send_btn.config(state="disabled" if busy else "normal")
        if busy:
            self.dots = 0
            self.animate()
        else:
            self.status.config(text="Ready")

    def animate(self):
        if not self.busy:
            return
        self.dots = (self.dots + 1) % 4
        self.status.config(text="Thinking" + "." * self.dots)
        self.root.after(400, self.animate)

    def copy_last(self):
        if self.last_reply:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.last_reply)
            self.status.config(text="Copied!")
            self.root.after(1200, lambda: self.status.config(text="Thinking" if self.busy else "Ready"))

    def reset(self):
        if self.busy:
            return
        self.chat = self._new_chat()
        self.last_reply = ""
        self.log.config(state="normal")
        self.log.delete("1.0", tk.END)
        self.log.config(state="disabled")
        self.add_message("bot", "New chat started. Ask me anything.")


if __name__ == "__main__":
    if "GEMINI_API_KEY" not in os.environ:
        raise SystemExit("Set the GEMINI_API_KEY environment variable first.")
    window = tk.Tk()
    ChatApp(window)
    window.mainloop()
