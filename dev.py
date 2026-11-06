"""Developer panel for this repo. Run: pythonw dev.py   (not part of the shipped app)
Buttons for the everyday jobs: run the pet, selftest, pull, release, open GitHub.
"""
import os, re, subprocess, sys, tkinter as tk, webbrowser
from tkinter import messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_URL = 'https://github.com/yuvancantcodeforshit/desktop-pet'


def current_version():
    with open(os.path.join(HERE, 'pet.py'), encoding='utf-8') as f:
        return re.search(r"VERSION = '([\d.]+)'", f.read()).group(1)


def bump(v):
    a, b, c = map(int, v.split('.'))
    return f'{a}.{b}.{c + 1}'


def console(*cmd):
    """Run in a new console window that stays open, so you can read the output."""
    subprocess.Popen([os.environ.get('ComSpec', 'cmd.exe'), '/k', *cmd], cwd=HERE,
                     creationflags=subprocess.CREATE_NEW_CONSOLE)


def git(*args):
    return subprocess.run(['git', *args], cwd=HERE, capture_output=True, text=True).stdout.strip()


class Panel:
    def __init__(self, root):
        self.root = root
        root.title('Desktop Pet - developer panel')
        root.resizable(False, False)
        f = tk.Frame(root, padx=14, pady=12)
        f.pack()
        self.info = tk.Label(f, justify='left', anchor='w')
        self.info.grid(row=0, column=0, columnspan=3, sticky='w', pady=(0, 10))

        tk.Label(f, text='Release version').grid(row=1, column=0, sticky='w')
        self.version = tk.Entry(f, width=10)
        self.version.grid(row=1, column=1, sticky='w')
        tk.Button(f, text='Release to everyone', bg='#f4d58d', command=self.release).grid(row=1, column=2, padx=6)

        buttons = [
            ('Run pet', lambda: subprocess.Popen([sys.executable, 'pet.py'], cwd=HERE)),
            ('Run selftest', lambda: console('python', 'pet.py', '--selftest')),
            ('git pull', lambda: console('git', 'pull')),
            ('git status', lambda: console('git', 'status')),
            ('Open releases page', lambda: webbrowser.open(REPO_URL + '/releases')),
            ('Open folder', lambda: os.startfile(HERE)),
            ('Refresh', self.refresh),
        ]
        for i, (text, cmd) in enumerate(buttons):
            tk.Button(f, text=text, width=18, command=cmd).grid(row=2 + i // 3, column=i % 3, pady=3, padx=3)
        self.refresh()

    def refresh(self):
        v = current_version()
        changes = git('status', '--porcelain')
        self.info.config(text=f'Current version: {v}\nBranch: {git("branch", "--show-current")}\n'
                              f'Uncommitted changes: {len(changes.splitlines()) if changes else "none"}')
        self.version.delete(0, 'end')
        self.version.insert(0, bump(v))

    def release(self):
        v = self.version.get().strip()
        if not re.fullmatch(r'\d+\.\d+\.\d+', v):
            messagebox.showerror('Release', 'Version must look like 1.0.3', parent=self.root)
            return
        if messagebox.askyesno('Release', f'Build, commit, push and publish v{v}?\n'
                                          'Every installed pet will update to it.', parent=self.root):
            console('powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', 'release.ps1', v)


if __name__ == '__main__':
    assert bump('1.0.9') == '1.0.10' and bump('2.3.4') == '2.3.5'
    Panel(tk.Tk()).root.mainloop()
