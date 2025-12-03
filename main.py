import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import os
import threading

# Configuration
DEFAULT_ANDROID_PATH = "/sdcard/"

class ADBFileManager:
    def __init__(self, root):
        self.root = root
        self.root.title("ADB File Manager (Linux <-> Android)")
        self.root.geometry("1000x700")
        
        # State
        self.local_cwd = os.getcwd()
        self.android_cwd = DEFAULT_ANDROID_PATH
        self.connected_device = None

        # Style
        self.style = ttk.Style()
        self.style.configure("Treeview", font=('Helvetica', 10), rowheight=25)
        self.style.configure("TButton", font=('Helvetica', 10, 'bold'))

        self._init_ui()
        self._check_connection()

    def _init_ui(self):
        # --- Top Bar (Status & Refresh) ---
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill=tk.X)
        
        self.lbl_status = ttk.Label(top_frame, text="Checking ADB connection...", foreground="blue")
        self.lbl_status.pack(side=tk.LEFT)
        
        btn_refresh = ttk.Button(top_frame, text="↻ Reconnect ADB", command=self._check_connection)
        btn_refresh.pack(side=tk.RIGHT)

        # --- Main Content (Dual Panes) ---
        paned_window = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned_window.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Left Frame (Local)
        left_frame = ttk.LabelFrame(paned_window, text="Local Machine (Linux)", padding=5)
        paned_window.add(left_frame, weight=1)
        
        self.lbl_local_path = ttk.Label(left_frame, text=self.local_cwd, relief="sunken", anchor="w")
        self.lbl_local_path.pack(fill=tk.X, pady=2)
        
        btn_frame_local = ttk.Frame(left_frame)
        btn_frame_local.pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame_local, text="⬆ Up", command=self.go_up_local, width=5).pack(side=tk.LEFT)
        ttk.Button(btn_frame_local, text="⟳", command=self.refresh_local, width=3).pack(side=tk.LEFT)

        self.tree_local = self._create_treeview(left_frame)
        self.tree_local.bind("<Double-1>", self.on_local_double_click)

        # Middle Buttons (Transfer Actions)
        center_frame = ttk.Frame(self.root, padding=5)
        # We don't pack this into the pane, we place it in the middle or bottom. 
        # Actually, let's put action buttons at the bottom for cleaner layout.
        
        # Right Frame (Android)
        right_frame = ttk.LabelFrame(paned_window, text="Android Device", padding=5)
        paned_window.add(right_frame, weight=1)

        self.lbl_android_path = ttk.Label(right_frame, text=self.android_cwd, relief="sunken", anchor="w")
        self.lbl_android_path.pack(fill=tk.X, pady=2)
        
        btn_frame_android = ttk.Frame(right_frame)
        btn_frame_android.pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame_android, text="⬆ Up", command=self.go_up_android, width=5).pack(side=tk.LEFT)
        ttk.Button(btn_frame_android, text="⟳", command=self.refresh_android, width=3).pack(side=tk.LEFT)

        self.tree_android = self._create_treeview(right_frame)
        self.tree_android.bind("<Double-1>", self.on_android_double_click)

        # --- Bottom Bar (Actions) ---
        action_frame = ttk.LabelFrame(self.root, text="Transfer Operations", padding=10)
        action_frame.pack(fill=tk.X, padx=10, pady=10)

        # Grid for centering
        action_frame.columnconfigure(0, weight=1)
        action_frame.columnconfigure(1, weight=1)
        action_frame.columnconfigure(2, weight=1)

        btn_push = ttk.Button(action_frame, text="Push to Android (Local -> Remote) ➡", command=self.push_file)
        btn_push.grid(row=0, column=2, padx=10, sticky="ew")

        btn_pull = ttk.Button(action_frame, text="⬅ Pull to Local (Remote -> Local)", command=self.pull_file)
        btn_pull.grid(row=0, column=0, padx=10, sticky="ew")
        
        ttk.Separator(action_frame, orient=tk.VERTICAL).grid(row=0, column=1, sticky="ns")

    def _create_treeview(self, parent):
        cols = ("Name", "Size", "Type")
        tree = ttk.Treeview(parent, columns=cols, show='headings', selectmode='browse')
        tree.heading("Name", text="Name")
        tree.heading("Size", text="Size")
        tree.heading("Type", text="Type")
        
        tree.column("Name", width=250)
        tree.column("Size", width=80, anchor="e")
        tree.column("Type", width=80, anchor="c")

        # Scrollbar
        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        return tree

    # --- ADB Logic ---
    def run_adb_cmd(self, cmd_list):
        """Runs an ADB command and returns (stdout, stderr)."""
        try:
            full_cmd = ['adb'] + cmd_list
            result = subprocess.run(full_cmd, capture_output=True, text=True)
            return result.stdout.strip(), result.stderr.strip()
        except FileNotFoundError:
            return None, "ADB executable not found in PATH."

    def _check_connection(self):
        def check():
            out, err = self.run_adb_cmd(['devices'])
            if err and "not found" in err:
                self.update_status("Error: ADB not found.", "red")
                return

            lines = out.split('\n')[1:] # Skip header
            devices = [line for line in lines if line.strip() and 'device' in line]
            
            if devices:
                self.connected_device = devices[0].split()[0]
                self.update_status(f"Connected: {self.connected_device}", "green")
                self.root.after(0, self.refresh_android)
                self.root.after(0, self.refresh_local)
            else:
                self.connected_device = None
                self.update_status("No device found. Connect via USB & enable Debugging.", "red")
                # Clear android tree
                for item in self.tree_android.get_children():
                    self.tree_android.delete(item)

        threading.Thread(target=check, daemon=True).start()

    def update_status(self, msg, color="black"):
        self.lbl_status.config(text=msg, foreground=color)

    # --- Local File System Logic ---
    def refresh_local(self):
        self.lbl_local_path.config(text=self.local_cwd)
        # Clear tree
        for item in self.tree_local.get_children():
            self.tree_local.delete(item)
        
        try:
            items = os.listdir(self.local_cwd)
            # Sort: Directories first, then files
            items.sort(key=lambda x: (not os.path.isdir(os.path.join(self.local_cwd, x)), x.lower()))

            for item in items:
                path = os.path.join(self.local_cwd, item)
                if os.path.isdir(path):
                    self.tree_local.insert('', 'end', values=(item, "", "Dir"), tags=('dir',))
                else:
                    size = f"{os.path.getsize(path) / 1024:.1f} KB"
                    self.tree_local.insert('', 'end', values=(item, size, "File"))
        except PermissionError:
            messagebox.showerror("Error", "Permission Denied")
            self.go_up_local()

    def go_up_local(self):
        self.local_cwd = os.path.dirname(self.local_cwd)
        self.refresh_local()

    def on_local_double_click(self, event):
        item_id = self.tree_local.selection()[0]
        item = self.tree_local.item(item_id)
        name = item['values'][0]
        itype = item['values'][2]

        if itype == "Dir":
            self.local_cwd = os.path.join(self.local_cwd, name)
            self.refresh_local()

    # --- Android File System Logic ---
    def refresh_android(self):
        if not self.connected_device:
            return

        def fetch():
            # Use ls -pl to get permissions and file types easily
            # -p appends / to directories
            cmd = ['shell', f'ls -p "{self.android_cwd}"']
            out, err = self.run_adb_cmd(cmd)
            
            items_data = []
            if out:
                lines = out.splitlines()
                for line in lines:
                    line = line.strip()
                    if not line: continue
                    
                    if line.endswith('/'):
                        # It's a directory
                        name = line[:-1]
                        items_data.append((name, "", "Dir"))
                    else:
                        # It's a file
                        items_data.append((line, "?", "File"))
            
            # Sort on UI thread
            self.root.after(0, lambda: self._update_android_tree(items_data))

        self.lbl_android_path.config(text=self.android_cwd)
        threading.Thread(target=fetch, daemon=True).start()

    def _update_android_tree(self, items):
        for item in self.tree_android.get_children():
            self.tree_android.delete(item)
        
        # Sort directories first
        items.sort(key=lambda x: (x[2] != "Dir", x[0].lower()))

        for name, size, ftype in items:
            self.tree_android.insert('', 'end', values=(name, size, ftype))

    def go_up_android(self):
        if self.android_cwd == "/":
            return
        
        # Simple string manipulation to go up
        new_path = os.path.dirname(self.android_cwd.rstrip('/'))
        if not new_path: 
            new_path = "/"
        if not new_path.endswith('/') and new_path != "/":
            new_path += "/"
        
        self.android_cwd = new_path
        self.refresh_android()

    def on_android_double_click(self, event):
        sel = self.tree_android.selection()
        if not sel: return
        
        item_id = sel[0]
        item = self.tree_android.item(item_id)
        name = item['values'][0]
        itype = item['values'][2]

        if itype == "Dir":
            if self.android_cwd == "/":
                self.android_cwd += name + "/"
            else:
                self.android_cwd = os.path.join(self.android_cwd, str(name)) + "/"
            self.refresh_android()

    # --- Transfer Logic ---
    def push_file(self):
        """ Local -> Android """
        sel = self.tree_local.selection()
        if not sel:
            messagebox.showinfo("Select File", "Please select a file on the Local side to push.")
            return
        
        item = self.tree_local.item(sel[0])
        name = item['values'][0]
        local_path = os.path.join(self.local_cwd, name)
        
        # Using a thread to prevent freezing
        def task():
            self.update_status(f"Pushing {name}...", "orange")
            out, err = self.run_adb_cmd(['push', local_path, self.android_cwd])
            if "error" in out.lower() or (err and "error" in err.lower()):
                 self.root.after(0, lambda: messagebox.showerror("Push Error", f"{out}\n{err}"))
            else:
                 self.root.after(0, self.refresh_android)
                 self.root.after(0, lambda: self.update_status("Push Complete", "green"))

        threading.Thread(target=task, daemon=True).start()

    def pull_file(self):
        """ Android -> Local """
        sel = self.tree_android.selection()
        if not sel:
            messagebox.showinfo("Select File", "Please select a file on the Android side to pull.")
            return

        item = self.tree_android.item(sel[0])
        name = item['values'][0]
        android_path = os.path.join(self.android_cwd, name) # Clean join usually works, but adb prefers /
        if self.android_cwd.endswith('/'):
            android_path = self.android_cwd + name
        else:
            android_path = self.android_cwd + '/' + name

        def task():
            self.update_status(f"Pulling {name}...", "orange")
            out, err = self.run_adb_cmd(['pull', android_path, self.local_cwd])
            if "error" in out.lower() or (err and "error" in err.lower()):
                 self.root.after(0, lambda: messagebox.showerror("Pull Error", f"{out}\n{err}"))
            else:
                 self.root.after(0, self.refresh_local)
                 self.root.after(0, lambda: self.update_status("Pull Complete", "green"))

        threading.Thread(target=task, daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    app = ADBFileManager(root)
    root.mainloop()