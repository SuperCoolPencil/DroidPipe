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

class TransferProgressWidget(tk.Frame):
    def __init__(self, parent, title, colors, fonts, cancel_cmd=None):
        super().__init__(parent, bg=colors['bg_light'], highlightthickness=1, highlightbackground=colors['border'])
        self.colors = colors
        self.pack(fill=tk.X, pady=2)
        
        header = tk.Frame(self, bg=colors['bg_light'])
        header.pack(fill=tk.X, padx=5, pady=2)
        
        self.lbl_title = tk.Label(header, text=title, font=fonts['small'], fg=colors['fg'], bg=colors['bg_light'])
        self.lbl_title.pack(side=tk.LEFT)
        
        if cancel_cmd:
            btn_cancel = tk.Button(header, text="X", font=fonts['small'], 
                                   bg=colors['bg_light'], fg=colors['error'],
                                   activebackground=colors['error'], activeforeground='white',
                                   relief='flat', bd=0, command=cancel_cmd, cursor='hand2')
            btn_cancel.pack(side=tk.RIGHT, padx=5)
        
        self.lbl_stats = tk.Label(header, text="", font=fonts['small'], fg=colors['fg'], bg=colors['bg_light'])
        self.lbl_stats.pack(side=tk.RIGHT, padx=10)
        
        self.lbl_percent = tk.Label(header, text="0%", font=fonts['small'], fg=colors['accent'], bg=colors['bg_light'])
        self.lbl_percent.pack(side=tk.RIGHT)
        
        self.canvas = tk.Canvas(self, height=4, bg=colors['bg_dark'], highlightthickness=0)
        self.canvas.pack(fill=tk.X, padx=5, pady=(0, 5))
        
        self.bind('<Configure>', self._on_resize)
        self.pct = 0

    def _on_resize(self, event):
        self._update_bar()

    def update_stats(self, stats_text):
        self.lbl_stats.config(text=stats_text)

    def update_title(self, new_title):
        self.lbl_title.config(text=new_title)

    def update_progress(self, pct):
        self.pct = pct
        self.lbl_percent.config(text=f"{int(pct)}%")
        self._update_bar()
        
    def _update_bar(self):
        # Draw progress bar on canvas
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        
        # Background
        self.canvas.create_rectangle(0, 0, w, h, fill=self.colors['bg_dark'], outline="")
        
        # Fill
        fill_w = int(w * (self.pct / 100))
        if fill_w > 0:
            self.canvas.create_rectangle(0, 0, fill_w, h, fill=self.colors['accent'], outline="")

    def complete(self, success=True, msg=None):
        if success:
            self.lbl_title.config(text="Transfer Complete", fg=self.colors['fg'])
            self.pct = 100
            self._update_bar()
        else:
            self.lbl_title.config(text=f"Error: {msg}", fg="#ff5555")


class DroidPipe:
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
        self.active_pane = "local" # Tracks which pane was last active
        
        # Search State
        self.search_buffer = ""
        self.search_last_time = 0
        self.search_timeout = 1.0 # Seconds to reset buffer

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
        
        
        self.sessions_frame = tk.Frame(top_frame, bg=self.colors['bg'])
        self.sessions_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=10)

        
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
        
        # --- NAV BUTTONS ---
        nav_buttons = [
            ("Home", lambda: self.go_home_local() if pane_type == "local" else self.go_home_android()),
            ("Up", lambda: self.go_up_local() if pane_type == "local" else self.go_up_android()),
            ("Refresh", lambda: self.refresh_local() if pane_type == "local" else self.refresh_android()),
            ("Delete", lambda: self.delete_selection(target=pane_type))
        ]
        
        for text, cmd in nav_buttons:
            style = 'danger_small' if text == "Delete" else 'small'
            btn = self._create_button(btn_frame, text, cmd, style=style)
            btn.pack(side=tk.LEFT, padx=2)
        
        # Disk Info Footer
        disk_label = tk.Label(frame, text="Checking disk space...", 
                             font=self.fonts['small'], 
                             fg='#808080', 
                             bg=self.colors['bg_light'],
                             anchor='e',
                             padx=10, pady=5)
        disk_label.pack(side=tk.BOTTOM, fill=tk.X)
        
        if pane_type == "local":
            self.lbl_local_disk = disk_label
        else:
            self.lbl_android_disk = disk_label

        tree_frame = tk.Frame(frame, bg=self.colors['bg_light'])
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        tree = self._create_treeview(tree_frame)
        
        # Bindings
        search_callback = lambda e, t=tree: self.on_key_search(e, t)
        
        if pane_type == "local":
            self.tree_local = tree
            tree.bind("<Double-1>", self.on_local_interact)
            tree.bind("<Return>", self.on_local_interact)
            tree.bind("<Escape>", lambda e: self.go_up_local())
            tree.bind("<Right>", lambda e: self.tree_android.focus_set())
            tree.bind("<Shift-Right>", self.request_push_confirm)
            tree.bind("<FocusIn>", lambda e: setattr(self, 'active_pane', 'local'))
            tree.bind("<Delete>", lambda e: self.delete_selection(target='local'))
            tree.bind("<Key>", search_callback) 
        else:
            self.tree_android = tree
            tree.bind("<Double-1>", self.on_android_interact)
            tree.bind("<Return>", self.on_android_interact)
            tree.bind("<Escape>", lambda e: self.go_up_android())
            tree.bind("<Left>", lambda e: self.tree_local.focus_set())
            tree.bind("<Shift-Left>", self.request_pull_confirm)
            tree.bind("<FocusIn>", lambda e: setattr(self, 'active_pane', 'android'))
            tree.bind("<Delete>", lambda e: self.delete_selection(target='android'))
            tree.bind("<Key>", search_callback)
        
        return frame

    def _create_treeview(self, parent):
        tree_frame = tk.Frame(parent, bg=self.colors['bg_dark'])
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        # Changed selectmode to extended for multiple selection
        tree = ttk.Treeview(tree_frame, 
                           columns=('Name', 'Size', 'Type'),
                           show='headings',
                           selectmode='extended',
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
        
        # Add sorting commands
        for col in ['Name', 'Size', 'Type']:
            tree.heading(col, text=col, command=lambda c=col: self.sort_column(tree, c, False))
        
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
                            text="Tip: Type to search, Click headers to sort, Shift+Click for multiple selection",
                            font=self.fonts['small'],
                            fg='#808080',
                            bg=self.colors['bg_light'])
        tip_label.pack(pady=(0, 10))

    # --- UTILS & SEARCH ---
    def select_first_item(self, tree):
        children = tree.get_children()
        if children:
            first = children[0]
            tree.selection_set(first)
            tree.focus(first)
            tree.see(first)

    def sort_column(self, tree, col, reverse):
        l = [(tree.set(k, col), k) for k in tree.get_children('')]
        
        # Helper for natural sort (File vs Folder logic handled mostly by refresh, 
        # but this does alphanumeric sort)
        try:
            # Try to sort by size as number if possible
            if col == 'Size':
                def size_val(x):
                    s = x[0].lower().replace('kb', '').replace('mb', '').replace('gb', '').strip()
                    if s == '?' or s == '': return -1
                    return float(s)
                l.sort(key=size_val, reverse=reverse)
            else:
                l.sort(key=lambda t: t[0].lower(), reverse=reverse)
        except:
            l.sort(reverse=reverse)

        for index, (val, k) in enumerate(l):
            tree.move(k, '', index)

        tree.heading(col, command=lambda: self.sort_column(tree, col, not reverse))

    def on_key_search(self, event, tree):
        if event.keysym in ('Up', 'Down', 'Left', 'Right', 'Return', 'Escape', 'Delete', 'Shift_L', 'Shift_R'):
            return
        
        now = time.time()
        if now - self.search_last_time > self.search_timeout:
            self.search_buffer = ""
        self.search_last_time = now
        
        if event.char and event.char.isprintable():
            self.search_buffer += event.char.lower()
            
            # Find matching item
            for child in tree.get_children():
                name = tree.item(child)['values'][0].lower()
                if name.startswith(self.search_buffer):
                    tree.selection_set(child)
                    tree.see(child)
                    tree.focus(child)
                    return

    def set_loading(self, is_loading):
        # Deprecated: The old usage was for main progress bar.
        # We can implement a small spinner in status or ignore.
        # - [x] Modify progress bar to show per-file progress visually <!-- id: 2 -->
        # - [x] Update status text to show "pushing x/y" <!-- id: 3 -->
        pass

    def _animate_progress(self):
        pass

    def set_progress(self, value):
        pass


    def update_status_indicator(self, color):
        self.status_indicator.itemconfig(self.status_circle, fill=color)

    def update_status(self, msg, color=None):
        if color is None:
            color = self.colors['fg']
        self.lbl_status.config(text=msg, fg=color)

    def _format_size(self, size_bytes):
        if size_bytes > 1024*1024*1024: return f"{size_bytes/(1024*1024*1024):.2f} GB"
        if size_bytes > 1024*1024: return f"{size_bytes/(1024*1024):.2f} MB"
        if size_bytes > 1024: return f"{size_bytes/1024:.2f} KB"
        return f"{size_bytes} B"

    def _get_recursive_files(self, local_paths):
        """Returns list of (abs_path, relative_path, size) tuples"""
        files_to_transfer = []
        for path in local_paths:
            if os.path.isfile(path):
                files_to_transfer.append((path, os.path.basename(path), os.path.getsize(path)))
            elif os.path.isdir(path):
                base_name = os.path.basename(path)
                for root, dirs, files in os.walk(path):
                    for f in files:
                        abs_path = os.path.join(root, f)
                        # Relative path from the parent of the selected directory
                        # If we select /a/b, and file is /a/b/c/d.txt, we want c/d.txt relative to b?
                        # No, if we push folder 'foo', it should end up as '.../foo' on device.
                        # So relative path should include 'foo'.
                        # If path is /home/user/foo, and file is /home/user/foo/bar.txt
                        # We want the destination to be <android_cwd>/foo/bar.txt
                        # So relative from os.path.dirname(path)
                        rel_path = os.path.relpath(abs_path, os.path.dirname(path))
                        files_to_transfer.append((abs_path, rel_path, os.path.getsize(abs_path)))
        return files_to_transfer

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

    def run_adb_transfer(self, cmd_list, progress_callback, cancel_event=None):
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
                if cancel_event and cancel_event.is_set():
                    process.terminate()
                    return "Cancelled", -2
                
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
            
            # Disk Usage
            try:
                total, used, free = shutil.disk_usage(self.local_cwd)
                free_str = self._format_size(free)
                total_str = self._format_size(total)
                self.lbl_local_disk.config(text=f"Local: {free_str} free / {total_str} total")
            except:
                self.lbl_local_disk.config(text="Disk info unavailable")

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
            # Use -l to get details including size
            cmd = ['shell', f'ls -l "{self.android_cwd}"']
            out, err = self.run_adb_cmd(cmd)
            self._loading = False
            self.root.after(0, lambda: self.set_loading(False))
            items_data = []
            if out:
                lines = out.splitlines()
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith('total'): continue
                    
                    parts = line.split()
                    if len(parts) < 4: continue # Skip malformed lines
                    
                    # Very basic parsing for 'ls -l' on Android (toybox)
                    # drwxrwx--x 3 root sdcard_rw 4096 2023-01-01 12:00 Name
                    perms = parts[0]
                    is_dir = perms.startswith('d')
                    
                    # Finding size and name is tricky as columns vary.
                    # Usually: perms links owner group size date time name
                    # Let's assume size is 4th index (5th item) if typical
                    # But safest is: First char 'd' = Folder.
                    
                    try:
                        # Attempt to find name index. Usually date is like YYYY-MM-DD
                        date_idx = -1
                        for i, p in enumerate(parts):
                            if '-' in p and ':' in parts[i+1]: # Finds date/time
                                date_idx = i
                                break
                        
                        if date_idx != -1:
                            size_idx = date_idx - 1
                            name_start = date_idx + 2
                            raw_size = parts[size_idx]
                            name = " ".join(parts[name_start:])
                        else:
                            # Fallback logic
                            name = parts[-1]
                            raw_size = "?"
                    except:
                        name = parts[-1]
                        raw_size = "?"

                    if name == "." or name == "..": continue

                    if is_dir:
                        items_data.append((name, "", "Folder"))
                    else:
                        try:
                            s = int(raw_size)
                            if s > 1024*1024: size_str = f"{s/(1024*1024):.1f} MB"
                            elif s > 1024: size_str = f"{s/1024:.1f} KB"
                            else: size_str = f"{s} B"
                        except: size_str = "?"
                        items_data.append((name, size_str, "File"))

            self.root.after(0, lambda: self._update_android_tree(items_data))
            
            # Disk Usage (df)
            try:
                # Use -k for 1K blocks explicitly if supported, or just default
                cmd_df = ['shell', f'df "{self.android_cwd}"']
                out_df, err_df = self.run_adb_cmd(cmd_df)
                if out_df:
                    lines = out_df.strip().splitlines()
                    # Filter for the line that likely contains our path or the last line
                    # Output usually: Filesystem 1K-blocks Used Available Use% Mounted on
                    # We pick the last line usually
                    if len(lines) >= 2:
                        parts = lines[-1].split()
                        # Assuming 1K blocks standard behavior for toybox/toolbox df
                        # parts indices: 0=fs, 1=total, 2=used, 3=avail
                        if len(parts) >= 4:
                            try:
                                total = int(parts[1]) * 1024
                                avail = int(parts[3]) * 1024
                                t_str = self._format_size(total)
                                a_str = self._format_size(avail)
                                self.root.after(0, lambda: self.lbl_android_disk.config(text=f"Android: {a_str} free / {t_str} total"))
                            except:
                                pass
            except Exception:
                pass

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
        if target is None:
            target = self.active_pane
        
        if target == "local":
            sel_items = self.tree_local.selection()
            if not sel_items: return
            
            count = len(sel_items)
            msg = f"Permanently delete {count} items from PC?" if count > 1 else f"Permanently delete '{self.tree_local.item(sel_items[0])['values'][0]}' from PC?"
            
            if messagebox.askyesno("Delete Local", msg):
                try:
                    for sel in sel_items:
                        name = str(self.tree_local.item(sel)['values'][0])
                        path = os.path.join(self.local_cwd, name)
                        if os.path.isdir(path):
                            shutil.rmtree(path)
                        else:
                            os.remove(path)
                    self.update_status(f"Deleted {count} items", self.colors['success'])
                    self.refresh_local()
                except Exception as e:
                    messagebox.showerror("Error", str(e))
        
        elif target == "android":
            sel_items = self.tree_android.selection()
            if not sel_items: return
            
            count = len(sel_items)
            msg = f"Permanently delete {count} items from Device?" if count > 1 else f"Permanently delete '{self.tree_android.item(sel_items[0])['values'][0]}' from Device?"
            
            if messagebox.askyesno("Delete Android", msg):
                def task():
                    for sel in sel_items:
                        name = str(self.tree_android.item(sel)['values'][0])
                        path = self.android_cwd + name if self.android_cwd.endswith('/') else self.android_cwd + '/' + name
                        escaped_path = f'"{path}"'
                        self.run_adb_cmd(['shell', 'rm', '-rf', escaped_path])
                    
                    self.root.after(0, lambda: self.update_status(f"Deleted {count} items", self.colors['success']))
                    self.root.after(0, self.refresh_android)
                threading.Thread(target=task, daemon=True).start()

    def request_push_confirm(self, event=None):
        sel_items = self.tree_local.selection()
        if not sel_items: return
        count = len(sel_items)
        name = str(self.tree_local.item(sel_items[0])['values'][0])
        msg = f"Push {count} items to Android?" if count > 1 else f"Push '{name}' to Android?"
        if messagebox.askyesno("Confirm", msg):
            self.push_file()

    def request_pull_confirm(self, event=None):
        sel_items = self.tree_android.selection()
        if not sel_items: return
        count = len(sel_items)
        name = str(self.tree_android.item(sel_items[0])['values'][0])
        msg = f"Pull {count} items from Android?" if count > 1 else f"Pull '{name}' from Android?"
        if messagebox.askyesno("Confirm", msg):
            self.pull_file()

    def pull_file(self):
        sel_items = self.tree_android.selection()
        if not sel_items: return
        
        total_items = len(sel_items)
        session_title = f"Pulling {total_items} item(s)"
        widget = TransferProgressWidget(self.sessions_frame, session_title, self.colors, self.fonts)
        # Pack new sessions at the top or bottom of the session frame? 
        # Side=TOP usually makes sense for a stack
        widget.pack(side=tk.TOP, fill=tk.X, pady=2)
        
        def task():
            try:
                # 1. Calculate stats with du
                paths_to_pull = []
                for sel in sel_items:
                    item = self.tree_android.item(sel)
                    name = str(item['values'][0])
                    p = self.android_cwd + name if self.android_cwd.endswith('/') else self.android_cwd + '/' + name
                    paths_to_pull.append(p)
                
                total_bytes = 0
                item_sizes = []
                try:
                    # Get size for each item to track progress accurately
                    for p in paths_to_pull:
                        # du -s -k for summary in KB. 
                        out, _ = self.run_adb_cmd(['shell', 'du', '-s', '-k', f'"{p}"'])
                        size_b = 0
                        if out:
                            # Output: 1234   /path/to/file
                            parts = out.split()
                            if parts:
                                try: size_b = int(parts[0]) * 1024
                                except: pass
                        item_sizes.append(size_b)
                        total_bytes += size_b
                except:
                    # Fallback if du fails
                    item_sizes = [0] * len(paths_to_pull)
                    total_bytes = 1
                
                if total_bytes == 0: total_bytes = 1
                
                start_time = time.time()
                transferred_so_far = 0
                
                for i, sel in enumerate(sel_items):
                    android_path = paths_to_pull[i]
                    current_item_size = item_sizes[i]
                    
                    def progress_wrapper(val, idx=i, c_size=current_item_size):
                        # Global percent based on item count (legacy) or bytes?
                        # Let's use bytes for accuracy if we have them
                        curr_file_bytes = int(c_size * (val / 100.0))
                        curr_total = transferred_so_far + curr_file_bytes
                        
                        # Use raw val for per-file progress if needed, 
                        # but widget only has one bar. 
                        # Let's show global progress on the bar.
                        global_p = (curr_total / total_bytes) * 100
                        if global_p > 100: global_p = 100
                        widget.update_progress(global_p)
                        
                        # Stats
                        elapsed = time.time() - start_time
                        if elapsed > 0.5:
                            speed = curr_total / elapsed
                            if speed > 0:
                                eta = (total_bytes - curr_total) / speed
                                speed_str = self._format_size(speed) + "/s"
                                eta_str = f"{int(eta // 60)}m {int(eta % 60)}s"
                                widget.update_stats(f"{speed_str} | ETA: {eta_str}")

                    self.run_adb_transfer(['pull', '-p', android_path, self.local_cwd], progress_wrapper)
                    transferred_so_far += current_item_size
                
                self.root.after(0, lambda: widget.complete(True))
                self.root.after(0, self.refresh_local)
                self.root.after(5000, widget.destroy)
            except Exception as e:
                self.root.after(0, lambda: widget.complete(False, str(e)))
            
        threading.Thread(target=task, daemon=True).start()


    def push_file(self):
        sel_items = self.tree_local.selection()
        if not sel_items: return
        
        # 1. Collect all files first
        local_paths = []
        for sel in sel_items:
            item = self.tree_local.item(sel)
            name = str(item['values'][0])
            local_paths.append(os.path.join(self.local_cwd, name))
            
        # Cancellation
        cancel_event = threading.Event()
        
        def on_cancel():
            cancel_event.set()
        
        # Setup Progress Widget
        count = len(sel_items)
        session_title = f"Preparing push..."
        widget = TransferProgressWidget(self.sessions_frame, session_title, self.colors, self.fonts, cancel_cmd=on_cancel)
        widget.pack(side=tk.TOP, fill=tk.X, pady=2)
        
        def task():
            try:
                files_to_transfer = self._get_recursive_files(local_paths)
                total_bytes = sum(f[2] for f in files_to_transfer)
                if total_bytes == 0: total_bytes = 1 # Avoid div/0
                
                formatted_total = self._format_size(total_bytes)
                
                transferred_bytes = 0
                is_cancelled = False
                
                start_time = time.time()

                for i, (abs_path, rel_path, size) in enumerate(files_to_transfer):
                    if cancel_event.is_set():
                        is_cancelled = True
                        break

                    # Update Title/Status initially for this file
                    pct = (transferred_bytes / total_bytes) * 100
                    widget.update_title(f"Pushing: {pct:.1f}%")
                    
                    # Update Progress Bar for current file (reset to 0 initially)
                    widget.update_progress(pct) # Actually let's show global progress on bar
                    
                    remote_dest = self.android_cwd + rel_path if self.android_cwd.endswith('/') else self.android_cwd + '/' + rel_path
                    remote_dir = os.path.dirname(remote_dest)
                    
                    def progress_wrapper(val):
                        # val is percentage of CURRENT file
                        
                        # Update global text
                        current_file_bytes = int(size * (val / 100.0))
                        current_global_bytes = transferred_bytes + current_file_bytes
                        global_pct = (current_global_bytes / total_bytes) * 100
                        widget.update_title(f"Pushing: {global_pct:.1f}%")
                        widget.update_progress(global_pct)

                        # Stats
                        elapsed = time.time() - start_time
                        if elapsed > 0.5:
                            speed = current_global_bytes / elapsed
                            if speed > 0:
                                eta = (total_bytes - current_global_bytes) / speed
                                speed_str = self._format_size(speed) + "/s"
                                eta_str = f"{int(eta // 60)}m {int(eta % 60)}s"
                                widget.update_stats(f"{speed_str} | ETA: {eta_str}")

                    # Using escaped paths just in case
                    cmd = ['push', '-p', abs_path, remote_dest] 
                    res, code = self.run_adb_transfer(cmd, progress_wrapper, cancel_event)
                    
                    if code == -2 or cancel_event.is_set(): # Cancelled
                        is_cancelled = True
                        # Cleanup partial file
                        self.run_adb_cmd(['shell', 'rm', '-f', f'"{remote_dest}"'])
                        break
                    
                    if code != 0:
                         widget.update_title(f"Error transferring {rel_path}")
                    
                    transferred_bytes += size
                
                if is_cancelled:
                     widget.complete(False, "Cancelled")
                else:
                    widget.complete(True)
                
                self.root.after(0, self.refresh_android)
                self.root.after(5000, widget.destroy)
                
            except Exception as e:
                self.root.after(0, lambda: widget.complete(False, str(e)))

        threading.Thread(target=task, daemon=True).start()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--debug", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
    
    root = tk.Tk()
    app = DroidPipe(root)
    root.mainloop()