import tkinter as tk
from tkinter import ttk, messagebox, font
import subprocess
import os
import shutil
import threading
import time
import re
import logging
import select
import argparse

# Handle pty import for Windows/Linux compatibility
try:
    import pty
except ImportError:
    pty = None

class ADBFileManager:
    def __init__(self, root):
        self.root = root
        self.root.title("DroidPipe - ADB File Manager")
        self.root.geometry("1200x800")
        
        # Color scheme - Dark theme
        self.colors = {
            'bg': '#1e1e1e',
            'fg': '#e0e0e0',
            'bg_dark': '#161616',
            'bg_light': '#2d2d2d',
            'accent': '#007acc',
            'accent_hover': '#1e8ad6',
            'success': '#4ec9b0',
            'error': '#f48771',
            'error_hover': '#d9534f',
            'warning': '#dcdcaa',
            'border': '#3e3e3e',
            'select': '#264f78',
            'folder': '#dcb67a',
            'file': '#cccccc'
        }
        
        self.root.configure(bg=self.colors['bg'])
        
        # State
        self.local_cwd = os.path.expanduser("~")
        self.android_cwd = "/storage/emulated/0/"
        self.connected_device = None
        self.active_pane = "local" # Tracks which pane was last active for keyboard shortcuts

        # --- LINUX FONT FIX ---
        base_family = "Liberation Sans" 
        
        self.fonts = {
            'default': font.Font(family=base_family, size=10),
            'bold': font.Font(family=base_family, size=10, weight="bold"),
            'small': font.Font(family=base_family, size=9),
            'large': font.Font(family=base_family, size=11),
            'title': font.Font(family=base_family, size=12, weight="bold")
        }
        # ----------------------

        self._init_ui()
        self._check_connection()

    def _init_ui(self):
        main_container = tk.Frame(self.root, bg=self.colors['bg'])
        main_container.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        # --- Top Bar ---
        top_frame = tk.Frame(main_container, bg=self.colors['bg'])
        top_frame.pack(fill=tk.X, pady=(0, 15))
        
        status_container = tk.Frame(top_frame, bg=self.colors['bg'])
        status_container.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.status_indicator = tk.Canvas(status_container, width=12, height=12, 
                                         highlightthickness=0, bg=self.colors['bg'])
        self.status_indicator.pack(side=tk.LEFT, padx=(0, 8))
        self.status_circle = self.status_indicator.create_oval(2, 2, 10, 10, 
                                                               fill='gray', outline='')
        
        self.lbl_status = tk.Label(status_container, 
                                   text="Checking ADB connection...",
                                   font=self.fonts['default'],
                                   fg=self.colors['fg'],
                                   bg=self.colors['bg'])
        self.lbl_status.pack(side=tk.LEFT)
        
        progress_frame = tk.Frame(top_frame, bg=self.colors['bg_dark'], 
                                 highlightthickness=1, highlightbackground=self.colors['border'])
        progress_frame.pack(side=tk.LEFT, padx=15)
        
        self.progress_canvas = tk.Canvas(progress_frame, width=250, height=20, 
                                        bg=self.colors['bg_dark'], 
                                        highlightthickness=0)
        self.progress_canvas.pack(side=tk.LEFT)
        self.progress_bar_rect = self.progress_canvas.create_rectangle(0, 0, 0, 20, 
                                                                       fill=self.colors['accent'], 
                                                                       outline='')
        
        self.lbl_percent = tk.Label(progress_frame, text="0%", 
                                    font=self.fonts['small'],
                                    fg=self.colors['fg'],
                                    bg=self.colors['bg_dark'],
                                    width=5)
        self.lbl_percent.pack(side=tk.LEFT, padx=(5, 5))
        
        btn_reconnect = self._create_button(top_frame, "[R] Reconnect", 
                                           self._check_connection,
                                           style='normal')
        btn_reconnect.pack(side=tk.RIGHT)

        # --- Main Content ---
        panes_container = tk.Frame(main_container, bg=self.colors['bg'])
        panes_container.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        left_pane = self._create_file_pane(panes_container, "Local Machine", 
                                          self.local_cwd, "local")
        left_pane.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
        
        right_pane = self._create_file_pane(panes_container, "Android Device", 
                                           self.android_cwd, "android")
        right_pane.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(8, 0))

        self._create_action_bar(main_container)

    def _create_file_pane(self, parent, title, initial_path, pane_type):
        frame = tk.Frame(parent, bg=self.colors['bg_light'], 
                        highlightthickness=1, highlightbackground=self.colors['border'])
        
        title_frame = tk.Frame(frame, bg=self.colors['bg_dark'])
        title_frame.pack(fill=tk.X)
        
        title_label = tk.Label(title_frame, text=title, 
                              font=self.fonts['title'],
                              fg=self.colors['fg'], 
                              bg=self.colors['bg_dark'],
                              pady=8)
        title_label.pack()
        
        path_frame = tk.Frame(frame, bg=self.colors['bg_light'])
        path_frame.pack(fill=tk.X, padx=10, pady=(10, 5))
        
        path_label = tk.Label(path_frame, text=initial_path,
                             font=self.fonts['small'],
                             fg=self.colors['accent'],
                             bg=self.colors['bg_dark'],
                             anchor='w',
                             padx=8, pady=6,
                             highlightthickness=1,
                             highlightbackground=self.colors['border'])
        path_label.pack(fill=tk.X)
        
        if pane_type == "local":
            self.lbl_local_path = path_label
        else:
            self.lbl_android_path = path_label
        
        btn_frame = tk.Frame(frame, bg=self.colors['bg_light'])
        btn_frame.pack(fill=tk.X, padx=10, pady=(5, 10))
        
        # --- NAV BUTTONS (Included Delete Here) ---
        nav_buttons = [
            ("Home", lambda: self.go_home_local() if pane_type == "local" else self.go_home_android()),
            ("Up", lambda: self.go_up_local() if pane_type == "local" else self.go_up_android()),
            ("Refresh", lambda: self.refresh_local() if pane_type == "local" else self.refresh_android()),
            ("Delete", lambda: self.delete_selection(target=pane_type))
        ]
        
        for text, cmd in nav_buttons:
            # Use danger_small style for the delete button
            style = 'danger_small' if text == "Delete" else 'small'
            btn = self._create_button(btn_frame, text, cmd, style=style)
            btn.pack(side=tk.LEFT, padx=2)
        
        tree_frame = tk.Frame(frame, bg=self.colors['bg_light'])
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        tree = self._create_treeview(tree_frame)
        
        if pane_type == "local":
            self.tree_local = tree
            tree.bind("<Double-1>", self.on_local_interact)
            tree.bind("<Return>", self.on_local_interact)
            tree.bind("<Escape>", lambda e: self.go_up_local())
            tree.bind("<Right>", lambda e: self.tree_android.focus_set())
            tree.bind("<Shift-Right>", self.request_push_confirm)
            tree.bind("<FocusIn>", lambda e: setattr(self, 'active_pane', 'local'))
            tree.bind("<Delete>", lambda e: self.delete_selection(target='local')) 
        else:
            self.tree_android = tree
            tree.bind("<Double-1>", self.on_android_interact)
            tree.bind("<Return>", self.on_android_interact)
            tree.bind("<Escape>", lambda e: self.go_up_android())
            tree.bind("<Left>", lambda e: self.tree_local.focus_set())
            tree.bind("<Shift-Left>", self.request_pull_confirm)
            tree.bind("<FocusIn>", lambda e: setattr(self, 'active_pane', 'android'))
            tree.bind("<Delete>", lambda e: self.delete_selection(target='android'))
        
        return frame

    def _create_treeview(self, parent):
        tree_frame = tk.Frame(parent, bg=self.colors['bg_dark'])
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        tree = ttk.Treeview(tree_frame, 
                           columns=('Name', 'Size', 'Type'),
                           show='headings',
                           selectmode='browse',
                           height=15)
        
        style = ttk.Style()
        style.theme_use('default')
        
        style.configure("Treeview",
                       background=self.colors['bg_dark'],
                       foreground=self.colors['fg'],
                       fieldbackground=self.colors['bg_dark'],
                       borderwidth=0,
                       font=self.fonts['default'], 
                       rowheight=28)
        
        style.configure("Treeview.Heading",
                       background=self.colors['bg'],
                       foreground=self.colors['fg'],
                       borderwidth=1,
                       font=self.fonts['bold'], 
                       relief='flat')
        
        style.map("Treeview",
                 background=[('selected', self.colors['select'])],
                 foreground=[('selected', self.colors['fg'])])
        
        style.map("Treeview.Heading",
                 background=[('active', self.colors['bg_light'])])
        
        tree.heading('Name', text='Name')
        tree.heading('Size', text='Size')
        tree.heading('Type', text='Type')
        
        tree.column('Name', width=300, minwidth=150)
        tree.column('Size', width=100, minwidth=80, anchor='e')
        tree.column('Type', width=90, minwidth=70, anchor='center')
        
        tree.grid(row=0, column=0, sticky='nsew')
        
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)
        
        return tree

    def _create_button(self, parent, text, command, style='normal'):
        if style == 'action':
            bg = self.colors['accent']
            fg = 'white'
            active_bg = self.colors['accent_hover']
            font_obj = self.fonts['bold']
            padx, pady = 20, 10
        elif style == 'danger':
            bg = self.colors['error']
            fg = 'white'
            active_bg = self.colors['error_hover']
            font_obj = self.fonts['bold']
            padx, pady = 15, 10
        elif style == 'danger_small':
            # Subtle danger button for nav bar
            bg = self.colors['bg']
            fg = self.colors['error']
            active_bg = self.colors['bg_light']
            font_obj = self.fonts['default']
            padx, pady = 10, 6
        elif style == 'small':
            bg = self.colors['bg']
            fg = self.colors['fg']
            active_bg = self.colors['bg_light']
            font_obj = self.fonts['default']
            padx, pady = 10, 6
        else:
            bg = self.colors['bg_light']
            fg = self.colors['fg']
            active_bg = self.colors['bg']
            font_obj = self.fonts['default']
            padx, pady = 12, 6
        
        btn = tk.Button(parent, text=text, command=command,
                       font=font_obj, 
                       bg=bg, fg=fg,
                       activebackground=active_bg,
                       activeforeground=fg,
                       relief='flat',
                       borderwidth=0,
                       padx=padx, pady=pady,
                       cursor='hand2')
        
        # Override hover for danger_small to keep text red
        if style == 'danger_small':
            btn.bind('<Enter>', lambda e: btn.config(bg=active_bg, fg=self.colors['error_hover']))
            btn.bind('<Leave>', lambda e: btn.config(bg=bg, fg=self.colors['error']))
        else:
            btn.bind('<Enter>', lambda e: btn.config(bg=active_bg))
            btn.bind('<Leave>', lambda e: btn.config(bg=bg))
        
        return btn

    def _create_action_bar(self, parent):
        frame = tk.Frame(parent, bg=self.colors['bg_light'],
                        highlightthickness=1, 
                        highlightbackground=self.colors['border'])
        frame.pack(fill=tk.X)
        
        title_frame = tk.Frame(frame, bg=self.colors['bg_dark'])
        title_frame.pack(fill=tk.X)
        
        title_label = tk.Label(title_frame, text="Transfer Operations",
                              font=self.fonts['title'],
                              fg=self.colors['fg'],
                              bg=self.colors['bg_dark'],
                              pady=8)
        title_label.pack()
        
        btn_container = tk.Frame(frame, bg=self.colors['bg_light'])
        btn_container.pack(pady=15)
        
        btn_pull = self._create_button(btn_container, 
                                       "< Pull (Shift+Left)",
                                       self.pull_file,
                                       style='action')
        btn_pull.pack(side=tk.LEFT, padx=10)
        
        # Removed central delete button
        
        sep = tk.Label(btn_container, text="<>",
                      font=self.fonts['title'],
                      fg=self.colors['accent'],
                      bg=self.colors['bg_light'])
        sep.pack(side=tk.LEFT, padx=20)
        
        btn_push = self._create_button(btn_container,
                                       "Push > (Shift+Right)",
                                       self.push_file,
                                       style='action')
        btn_push.pack(side=tk.LEFT, padx=10)
        
        tip_label = tk.Label(frame, 
                            text="Tip: Use arrow keys to navigate, Shift+Arrow to transfer, Delete key to remove",
                            font=self.fonts['small'],
                            fg='#808080',
                            bg=self.colors['bg_light'])
        tip_label.pack(pady=(0, 10))

    # --- UTILS & ADB ---
    def select_first_item(self, tree):
        children = tree.get_children()
        if children:
            first = children[0]
            tree.selection_set(first)
            tree.focus(first)
            tree.see(first)

    def set_loading(self, is_loading):
        if is_loading:
            self._animate_progress()
            self.lbl_percent.config(text="...")
        else:
            self.progress_canvas.itemconfig(self.progress_bar_rect, fill=self.colors['accent'])
            self.progress_canvas.coords(self.progress_bar_rect, 0, 0, 0, 20)
            self.lbl_percent.config(text="0%")

    def _animate_progress(self):
        if not hasattr(self, '_progress_pos'):
            self._progress_pos = 0
        self._progress_pos = (self._progress_pos + 5) % 250
        width = 50
        self.progress_canvas.coords(self.progress_bar_rect, 
                                   self._progress_pos, 0, 
                                   self._progress_pos + width, 20)
        if hasattr(self, '_loading') and self._loading:
            self.root.after(20, self._animate_progress)

    def set_progress(self, value):
        width = int((value / 100) * 250)
        self.progress_canvas.coords(self.progress_bar_rect, 0, 0, width, 20)
        self.progress_canvas.itemconfig(self.progress_bar_rect, fill=self.colors['success'])
        self.lbl_percent.config(text=f"{int(value)}%")

    def update_status_indicator(self, color):
        self.status_indicator.itemconfig(self.status_circle, fill=color)

    def update_status(self, msg, color=None):
        if color is None:
            color = self.colors['fg']
        self.lbl_status.config(text=msg, fg=color)

    def run_adb_cmd(self, cmd_list):
        logging.debug(f"Running ADB command: {' '.join(cmd_list)}")
        try:
            full_cmd = ['adb'] + cmd_list
            result = subprocess.run(full_cmd, capture_output=True, text=True,
                                  encoding='utf-8', errors='replace')
            return result.stdout.strip(), result.stderr.strip()
        except FileNotFoundError:
            logging.error("ADB executable not found in PATH.")
            return None, "ADB executable not found in PATH."

    def run_adb_transfer(self, cmd_list, progress_callback):
        # Linux Support (pty)
        if pty is None: 
            out, err = self.run_adb_cmd(cmd_list)
            progress_callback(100)
            return out, 0

        master_fd, slave_fd = pty.openpty()
        try:
            full_cmd = ['adb'] + cmd_list
            process = subprocess.Popen(full_cmd, stdout=slave_fd, stderr=slave_fd, close_fds=True)
            os.close(slave_fd)
            output_buffer = b""
            while True:
                r, w, e = select.select([master_fd], [], [], 0.1)
                if master_fd in r:
                    try:
                        chunk = os.read(master_fd, 1024)
                        if not chunk: break
                        output_buffer += chunk
                        output_buffer = output_buffer[-1024:]
                        try:
                            current_str = output_buffer.decode('utf-8', errors='ignore')
                            matches = list(re.finditer(r'(\d+)%', current_str))
                            if matches:
                                p = int(matches[-1].group(1))
                                if progress_callback:
                                    self.root.after(0, lambda val=p: progress_callback(val))
                        except: pass
                    except OSError: break
                elif process.poll() is not None: break
            process.wait()
            return "Transfer finished", process.returncode
        except Exception as e:
            if 'slave_fd' in locals(): os.close(slave_fd)
            if 'master_fd' in locals(): os.close(master_fd)
            return str(e), -1
        finally:
            if 'master_fd' in locals():
                try: os.close(master_fd)
                except: pass

    def _check_connection(self):
        def check():
            logging.info("Checking ADB connection...")
            self._loading = True
            self.root.after(0, lambda: self.set_loading(True))
            out, err = self.run_adb_cmd(['devices'])
            self._loading = False
            self.root.after(0, lambda: self.set_loading(False))

            if err and "not found" in err:
                self.update_status("Error: ADB not found", self.colors['error'])
                self.root.after(0, lambda: self.update_status_indicator(self.colors['error']))
                return

            if not out:
                self.connected_device = None
                self.update_status("ADB Error: No output", self.colors['error'])
                self.root.after(0, lambda: self.update_status_indicator(self.colors['error']))
                return

            lines = out.split('\n')[1:]
            devices = [line for line in lines if line.strip() and 'device' in line]
            if devices:
                self.connected_device = devices[0].split()[0]
                self.update_status(f"Connected: {self.connected_device}", self.colors['success'])
                self.root.after(0, lambda: self.update_status_indicator(self.colors['success']))
                self.root.after(0, self.refresh_android)
                self.root.after(0, self.refresh_local)
            else:
                self.connected_device = None
                self.update_status("No device found", self.colors['warning'])
                self.root.after(0, lambda: self.update_status_indicator(self.colors['warning']))
                for item in self.tree_android.get_children():
                    self.tree_android.delete(item)
        threading.Thread(target=check, daemon=True).start()

    def refresh_local(self):
        self.lbl_local_path.config(text=self.local_cwd)
        for item in self.tree_local.get_children():
            self.tree_local.delete(item)
        try:
            items = os.listdir(self.local_cwd)
            items.sort(key=lambda x: (not os.path.isdir(os.path.join(self.local_cwd, x)), x.lower()))
            for item in items:
                path = os.path.join(self.local_cwd, item)
                if os.path.isdir(path):
                    self.tree_local.insert('', 'end', values=(item, "", "Folder"))
                else:
                    try: size = f"{os.path.getsize(path) / 1024:.1f} KB"
                    except: size = "?"
                    self.tree_local.insert('', 'end', values=(item, size, "File"))
            self.select_first_item(self.tree_local)
        except PermissionError:
            self.go_up_local()

    def go_up_local(self):
        self.local_cwd = os.path.dirname(self.local_cwd)
        self.refresh_local()

    def go_home_local(self):
        self.local_cwd = os.path.expanduser("~")
        self.refresh_local()

    def on_local_interact(self, event):
        sel = self.tree_local.selection()
        if not sel: return
        item = self.tree_local.item(sel[0])
        name = str(item['values'][0])
        itype = item['values'][2]
        if itype == "Folder":
            self.local_cwd = os.path.join(self.local_cwd, name)
            self.refresh_local()

    def refresh_android(self):
        if not self.connected_device: return
        def fetch():
            self._loading = True
            self.root.after(0, lambda: self.set_loading(True))
            cmd = ['shell', f'ls -p "{self.android_cwd}"']
            out, err = self.run_adb_cmd(cmd)
            self._loading = False
            self.root.after(0, lambda: self.set_loading(False))
            items_data = []
            if out:
                lines = out.splitlines()
                for line in lines:
                    line = line.strip()
                    if not line: continue
                    if line.endswith('/'): items_data.append((line[:-1], "", "Folder"))
                    else: items_data.append((line, "?", "File"))
            self.root.after(0, lambda: self._update_android_tree(items_data))
        self.lbl_android_path.config(text=self.android_cwd)
        threading.Thread(target=fetch, daemon=True).start()

    def _update_android_tree(self, items):
        for item in self.tree_android.get_children():
            self.tree_android.delete(item)
        items.sort(key=lambda x: (x[2] != "Folder", x[0].lower()))
        for name, size, ftype in items:
            self.tree_android.insert('', 'end', values=(name, size, ftype))
        self.select_first_item(self.tree_android)

    def go_up_android(self):
        if self.android_cwd == "/": return
        new_path = os.path.dirname(self.android_cwd.rstrip('/'))
        if not new_path: new_path = "/"
        if not new_path.endswith('/') and new_path != "/": new_path += "/"
        self.android_cwd = new_path
        self.refresh_android()

    def go_home_android(self):
        self.android_cwd = "/storage/emulated/0/"
        self.refresh_android()

    def on_android_interact(self, event):
        sel = self.tree_android.selection()
        if not sel: return
        item = self.tree_android.item(sel[0])
        name = str(item['values'][0])
        itype = item['values'][2]
        if itype == "Folder":
            if self.android_cwd == "/": self.android_cwd += name + "/"
            else: self.android_cwd = os.path.join(self.android_cwd, name) + "/"
            self.refresh_android()

    # --- ACTION HANDLERS ---
    def delete_selection(self, target=None, event=None):
        """ Handles Deletion for both Local and Android based on context or explicit target """
        
        # If target not explicitly passed (e.g. keyboard shortcut), use active pane
        if target is None:
            target = self.active_pane
        
        if target == "local":
            sel = self.tree_local.selection()
            if not sel: return
            item = self.tree_local.item(sel[0])
            name = str(item['values'][0])
            path = os.path.join(self.local_cwd, name)
            
            if messagebox.askyesno("Delete Local", f"Permanently delete '{name}' from PC?"):
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path)
                    else:
                        os.remove(path)
                    self.update_status(f"Deleted: {name}", self.colors['success'])
                    self.refresh_local()
                except Exception as e:
                    messagebox.showerror("Error", str(e))
        
        elif target == "android":
            sel = self.tree_android.selection()
            if not sel: return
            item = self.tree_android.item(sel[0])
            name = str(item['values'][0])
            path = self.android_cwd + name if self.android_cwd.endswith('/') else self.android_cwd + '/' + name
            
            # Escape spaces for ADB
            escaped_path = f'"{path}"'
            
            if messagebox.askyesno("Delete Android", f"Permanently delete '{name}' from Device?"):
                def task():
                    out, err = self.run_adb_cmd(['shell', 'rm', '-rf', escaped_path])
                    if err:
                        self.root.after(0, lambda: messagebox.showerror("ADB Error", err))
                    else:
                        self.root.after(0, lambda: self.update_status(f"Deleted: {name}", self.colors['success']))
                        self.root.after(0, self.refresh_android)
                threading.Thread(target=task, daemon=True).start()

    def request_push_confirm(self, event=None):
        sel = self.tree_local.selection()
        if not sel: return
        name = str(self.tree_local.item(sel[0])['values'][0])
        if messagebox.askyesno("Confirm", f"Push '{name}' to Android?"):
            self.push_file()

    def request_pull_confirm(self, event=None):
        sel = self.tree_android.selection()
        if not sel: return
        name = str(self.tree_android.item(sel[0])['values'][0])
        if messagebox.askyesno("Confirm", f"Pull '{name}' from Android?"):
            self.pull_file()

    def pull_file(self):
        sel = self.tree_android.selection()
        if not sel: return
        item = self.tree_android.item(sel[0])
        name = str(item['values'][0])
        android_path = self.android_cwd + name if self.android_cwd.endswith('/') else self.android_cwd + '/' + name
        def task():
            self.root.after(0, lambda: self.set_progress(0))
            self.update_status(f"Pulling {name}...", self.colors['accent'])
            out, ret_code = self.run_adb_transfer(['pull', '-p', android_path, self.local_cwd], lambda val: self.set_progress(val))
            self.root.after(0, lambda: self.set_loading(False))
            if ret_code != 0:
                self.root.after(0, lambda: messagebox.showerror("Error", out))
                self.root.after(0, lambda: self.update_status("Failed", self.colors['error']))
            else:
                self.root.after(0, self.refresh_local)
                self.root.after(0, lambda: self.update_status(f"Done: {name}", self.colors['success']))
        threading.Thread(target=task, daemon=True).start()

    def push_file(self):
        sel = self.tree_local.selection()
        if not sel: return
        item = self.tree_local.item(sel[0])
        name = str(item['values'][0])
        local_path = os.path.join(self.local_cwd, name)
        def task():
            self.root.after(0, lambda: self.set_progress(0))
            self.update_status(f"Pushing {name}...", self.colors['accent'])
            out, ret_code = self.run_adb_transfer(['push', '-p', local_path, self.android_cwd], lambda val: self.set_progress(val))
            self.root.after(0, lambda: self.set_loading(False))
            if ret_code != 0:
                self.root.after(0, lambda: messagebox.showerror("Error", out))
                self.root.after(0, lambda: self.update_status("Failed", self.colors['error']))
            else:
                self.root.after(0, self.refresh_android)
                self.root.after(0, lambda: self.update_status(f"Done: {name}", self.colors['success']))
        threading.Thread(target=task, daemon=True).start()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--debug", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
    
    root = tk.Tk()
    app = ADBFileManager(root)
    root.mainloop()