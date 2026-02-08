"""
FM4 Car Audio Tuner - First-Run Setup
Downloads QuickBMS and extracts game tuning ZIPs.
Run this before using the tuner, or let the tuner run it automatically.
"""

import io
import os
import shutil
import struct
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import urllib.request
import zipfile

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

QUICKBMS_DIR = os.path.join(BASE_DIR, "quickbms")
QUICKBMS_EXE = os.path.join(QUICKBMS_DIR, "quickbms.exe")
ZIP_BMS = os.path.join(BASE_DIR, "zip.bms")
ET_DIR = os.path.join(BASE_DIR, "enginetuning_extracted")
HT_DIR = os.path.join(BASE_DIR, "harmonictuning_extracted")

QUICKBMS_URL = "https://aluigi.altervista.org/papers/quickbms.zip"

# zip.bms content - the BMS script needed for Xbox 360 ZIP extraction
ZIP_BMS_CONTENT = r'''# ZIP files example 0.4.12
# more info: http://www.pkware.com/documents/casestudies/APPNOTE.TXT
# script for QuickBMS http://quickbms.aluigi.org

# put the password here, it supports both ZipCrypto and AES
set ZIP_PASSWORD string ""

quickbmsver "0.7.4"

get EXE_SIGN long
goto 0
if EXE_SIGN == 0x00905a4d
    get EXT extension
    if EXT == "exe" || EXT == "dll"
        findloc OFFSET string "PK\x03\x04"
        goto OFFSET
    endif
elif EXE_SIGN == 0x02014b50
    findloc OFFSET binary "\x50\x4b\x03\x04"
    goto OFFSET
endif

savepos OFFSET
set ZIP_SIGN short 0x0403
goto OFFSET
getdstring ZIP_CENTRAL_SEARCH 6 # PK_sign + sign + ver
goto OFFSET
get DUMMY short
get ZIP_SIGN short

math ALTERNATIVE_MODE = 0

math FIRST_FILE = 1
goto OFFSET
get zip_filesize asize
for offset = offset < zip_filesize
    get PK_sign short
    get sign short
    if sign == ZIP_SIGN
        get ver             short
        get flag            short
        get method          short
        get modtime         short
        get moddate         short
        get zip_crc         long
        get comp_size       long
        get uncomp_size     long
        get name_len        short
        get extra_len       short
        getdstring name     name_len
        getdstring extra    extra_len
        savepos offset

        if FIRST_FILE != 0
            math FIRST_FILE = 0
            if flag & 8
            if zip_crc == 0
            if comp_size == 0
                goto -0x16
                get PK_sign short
                idstring "\x05\x06"
                get disk_num        short
                get disk_start      short
                get central_entries short
                get central_entries short
                get central_size    long
                get central_offset  long
                get comm_len        short
                getdstring comment  comm_len
                math ALTERNATIVE_MODE   = 1
                math ALTERNATIVE_OFFSET = central_offset
                math ALTERNATIVE_comp_size = 0
                math ALTERNATIVE_uncomp_size = 0
                math ALTERNATIVE_zip_crc = 0
                set NAME string "/"
                math uncomp_size = 0
            endif
            endif
            endif
        endif

        if ALTERNATIVE_MODE != 0
            math comp_size   = ALTERNATIVE_comp_size
            math uncomp_size = ALTERNATIVE_uncomp_size
            math zip_crc     = ALTERNATIVE_zip_crc
        endif

        if extra_len >= 20
            getvarchr extra_id extra 0 short
            if extra_id == 0x0001
            if comp_size == 0xffffffff
                getvarchr uncomp_size 4 longlong
                getvarchr comp_size 12 longlong
            endif
            endif
        endif

        if comp_size & 0x80000000
        if comp_size u> zip_filesize
            math comp_size ^= 0xffffffff
            math uncomp_size ^= 0xffffffff
        endif
        endif
        if name_len & 0x80000000
            math name_len ^= 0xffffffff
        endif
        if extra_len & 0x80000000
            math extra_len ^= 0xffffffff
        endif

        if flag & 1
            if ZIP_PASSWORD == ""
                print "the file is encrypted, you must set ZIP_PASSWORD in the script!"
            endif
            math method_backup = method
            if method == 99
                getvarchr AES_EXTRA1 extra 0 short
                getvarchr AES_EXTRA2 extra 2 short
                getvarchr AES_EXTRA3 extra 4 short
                getvarchr AES_EXTRA4 extra 6 short
                getvarchr AES_EXTRA5 extra 8 byte
                getvarchr AES_EXTRA6 extra 9 short
                math method = AES_EXTRA6
                if AES_EXTRA5 == 0x01
                    math AES_KEY_SIZE = 8
                    set AES_ALGO string "ZIP_AES128"
                elif AES_EXTRA5 == 0x02
                    math AES_KEY_SIZE = 12
                    set AES_ALGO string "ZIP_AES192"
                elif AES_EXTRA5 == 0x03
                    math AES_KEY_SIZE = 16
                    set AES_ALGO string "ZIP_AES256"
                else
                    print "Error: invalid AES_EXTRA5 %AES_EXTRA5%"
                    cleanexit
                endif
                getdstring AES_SALT AES_KEY_SIZE
                xmath offset    "offset    + (AES_KEY_SIZE + 2)"
                xmath comp_size "comp_size - (AES_KEY_SIZE + 2 + 10)"
                strlen ZIP_PASSWORD_LEN ZIP_PASSWORD
                encryption AES_ALGO ZIP_PASSWORD AES_SALT 0 ZIP_PASSWORD_LEN
            else
                encryption zipcrypto ZIP_PASSWORD 1
            endif
        endif

        if method == 0
            Log name offset comp_size
        else
            if method == 8
                ComType deflate
            elif method == 1
                ComType shrink
            elif method == 2
                ComType reduce1
            elif method == 3
                ComType reduce2
            elif method == 4
                ComType reduce3
            elif method == 5
                ComType reduce4
            elif method == 6
                ComType pkware
            elif method == 9
                ComType deflate64
            elif method == 10
                ComType pkware
            elif method == 12
                ComType bzip2
            elif method == 13
                ComType XMemDecompress
            elif method == 14
                ComType lzmaefs
            elif method == 15
                ComType oodle
            elif method == 18
                ComType terse
            elif method == 21
                ComType XMemDecompress
            elif method == 24
                comtype lzma86dechead
            elif method == 28
                ComType lz4f
            elif method == 34
                ComType brotli
            elif method == 64
                ComType darksector
            elif method == 95
                comtype LZMA2_EFS0
                getdstring XZ_MAGIC 6
                get XZ_FLAGS0 byte
                get XZ_FLAGS byte
                get XZ_CRC32 long
                xmath DUMMY "1 << ((((XZ_FLAGS & 0xf) - 1) / 3) + 2)"
                getdstring DUMMY DUMMY
                savepos tmp
                xmath comp_size "comp_size - (tmp - offset)"
                math offset = tmp
            elif method == 96
                ComType copy
                math uncomp_size = comp_size
                string name + ".jpg"
            elif method == 97
                ComType copy
                math uncomp_size = comp_size
                string name + ".wv"
            elif method == 98
                ComType ppmd
            elif method == 99
                ComType lzfse
            else
                print "unsupported compression method %method%"
                cleanexit
            endif
            CLog name offset comp_size uncomp_size
        endif

        if flag & 1
            encryption "" ""
            if method_backup == 99
                math offset += 10
            endif
        endif

        math offset += comp_size
        goto offset

        if ALTERNATIVE_MODE != 0
            goto ALTERNATIVE_OFFSET
        endif

    elif sign == 0x0806
        get extra_len       long
        getdstring extra    extra_len

    elif sign == 0x0201
        get ver_made        short
        get ver_need        short
        get flag            short
        get method          short
        get modtime         short
        get moddate         short
        get zip_crc         long
        get comp_size       long
        get uncomp_size     long
        get name_len        short
        get extra_len       short
        get comm_len        short
        get disknum         short
        get int_attr        short
        get ext_attr        long
        get rel_offset      long
        getdstring name     name_len
        getdstring extra    extra_len
        getdstring comment  comm_len

        if ALTERNATIVE_MODE != 0
            math ALTERNATIVE_comp_size = comp_size
            math ALTERNATIVE_uncomp_size = uncomp_size
            math ALTERNATIVE_zip_crc = zip_crc
            savepos ALTERNATIVE_OFFSET
            goto rel_offset
        endif

    elif sign == 0x0505
        get sign_len        long
        getdstring sign     sign_len

    elif sign == 0x0606
        get dir_record      longlong
        get ver_made        short
        get ver_need        short
        get num_disk        long
        get num_disk2       long
        get tot_entries     longlong
        get tot_entries2    longlong
        get central_size    longlong
        get central_offset  longlong
        print "Error: zip64 extensible data sector not implemented, contact me"
        cleanexit

    elif sign == 0x0706
        get start_central   long
        get end_central     longlong
        get disks           long

    elif sign == 0x0605
        get disk_num        short
        get disk_start      short
        get central_entries short
        get central_entries short
        get central_size    long
        get central_offset  long
        get comm_len        short
        getdstring comment  comm_len

    elif sign == 0x0807
        get zip_crc         long
        get comp_size       long
        get uncomp_size     long

    elif sign == 0x3030
        # nothing?

    else
        print "...search ZIP signature..."
        findloc NEW_OFFSET binary ZIP_CENTRAL_SEARCH ""
        if NEW_OFFSET == ""
            xmath COVERAGE "offset / (zip_filesize / 100)"
            set COVERAGE_OK string "not fully covered, lot of data remaining"
            if COVERAGE >= 90
                set COVERAGE_OK string "fully covered, probably no remaining data"
            endif
            print "\nError: unknown ZIP signature %sign|x% at offset %offset|x%\n       if the other files have been extracted correctly it's all ok,\n       maybe this is just the end of file:\n\n       OFFSET   %offset|x%\n       ZIP SIZE %zip_filesize|x%\n       COVERAGE %COVERAGE% / 100   (%COVERAGE_OK%)"
            cleanexit
        endif
        goto NEW_OFFSET
    endif

    savepos offset
next
'''


def check_needs_setup():
    """Return list of missing components."""
    missing = []
    if not os.path.isfile(QUICKBMS_EXE):
        missing.append("QuickBMS")
    if not os.path.isfile(ZIP_BMS):
        missing.append("zip.bms script")
    return missing


def check_needs_extraction():
    """Check if game ZIPs need to be extracted."""
    needs = []
    if not os.path.isdir(ET_DIR) or not os.listdir(ET_DIR):
        needs.append("enginetuning")
    if not os.path.isdir(HT_DIR) or not os.listdir(HT_DIR):
        needs.append("harmonictuning")
    return needs


class SetupWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("FM4 Car Audio Tuner - Setup")
        self.root.geometry("550x400")
        self.root.resizable(False, False)

        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="FM4 Car Audio Tuner - First Run Setup",
                  font=("Segoe UI", 12, "bold")).pack(pady=(0, 8))

        ttk.Label(main, text=(
            "This setup will:\n"
            "  1. Download QuickBMS (required for Xbox 360 ZIP handling)\n"
            "  2. Create the zip.bms extraction script\n"
            "  3. Locate and extract your game's tuning ZIP files\n\n"
            "You will need your Forza Motorsport 4 game files accessible\n"
            "on this computer (e.g. from an Xbox 360 disc dump or Xenia)."),
            wraplength=500, justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 8))

        # Game root selection
        path_frame = ttk.LabelFrame(main, text="Game Root Directory", padding=4)
        path_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(path_frame, text=(
            "Select the root folder containing your FM4 game files.\n"
            "The tool will search for enginetuning.zip and harmonictuning.zip."),
            wraplength=480, font=("Segoe UI", 8)).pack(anchor=tk.W)
        path_row = ttk.Frame(path_frame)
        path_row.pack(fill=tk.X, pady=(4, 0))
        self.game_path_var = tk.StringVar()
        ttk.Entry(path_row, textvariable=self.game_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(path_row, text="Browse...", command=self._browse).pack(side=tk.LEFT, padx=(4, 0))

        # Progress
        self.progress_var = tk.StringVar(value="Ready")
        ttk.Label(main, textvariable=self.progress_var, foreground="gray").pack(anchor=tk.W, pady=(4, 2))
        self.progress_bar = ttk.Progressbar(main, mode="determinate", maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=(0, 8))

        # Log
        self.log_text = tk.Text(main, height=6, font=("Consolas", 8), state=tk.DISABLED, bg="#1e1e1e", fg="#cccccc")
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Buttons
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(8, 0))
        self.run_btn = ttk.Button(btn_frame, text="Run Setup", command=self._run_setup)
        self.run_btn.pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Skip (Advanced)", command=self._skip).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(btn_frame, text="Close", command=self.root.destroy).pack(side=tk.RIGHT)

        self.success = False

    def _browse(self):
        path = filedialog.askdirectory(title="Select game root directory")
        if path:
            self.game_path_var.set(path)

    def _log(self, msg):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
        self.root.update()

    def _skip(self):
        self.success = True
        self.root.destroy()

    def _run_setup(self):
        self.run_btn.configure(state=tk.DISABLED)

        try:
            # Step 1: Download QuickBMS
            if not os.path.isfile(QUICKBMS_EXE):
                self.progress_var.set("Downloading QuickBMS...")
                self.progress_bar["value"] = 10
                self._log("Downloading QuickBMS from aluigi.altervista.org...")

                try:
                    req = urllib.request.Request(QUICKBMS_URL, headers={
                        "User-Agent": "FM4CarAudioTuner-Setup/1.0"
                    })
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        data = resp.read()
                    self._log(f"Downloaded {len(data)} bytes")

                    os.makedirs(QUICKBMS_DIR, exist_ok=True)
                    with zipfile.ZipFile(io.BytesIO(data)) as zf:
                        zf.extractall(QUICKBMS_DIR)
                    self._log(f"Extracted QuickBMS to {QUICKBMS_DIR}")
                except Exception as e:
                    self._log(f"ERROR downloading QuickBMS: {e}")
                    self._log("You can manually download from: https://aluigi.altervista.org/quickbms.htm")
                    self._log(f"Extract quickbms.exe into: {QUICKBMS_DIR}")
                    self.run_btn.configure(state=tk.NORMAL)
                    return
            else:
                self._log("QuickBMS already installed.")

            self.progress_bar["value"] = 30

            # Step 2: Create zip.bms
            if not os.path.isfile(ZIP_BMS):
                self.progress_var.set("Creating zip.bms script...")
                with open(ZIP_BMS, "w", newline="\n") as f:
                    f.write(ZIP_BMS_CONTENT)
                self._log("Created zip.bms script")
            else:
                self._log("zip.bms already exists.")

            self.progress_bar["value"] = 40

            # Step 3: Find and extract game ZIPs
            game_root = self.game_path_var.get().strip()
            if not game_root:
                self._log("No game root specified - skipping ZIP extraction.")
                self._log("You can use Find Files in the tuner later to locate game files.")
                self.progress_bar["value"] = 100
                self.progress_var.set("Setup complete (partial - no game ZIPs extracted)")
                self.success = True
                messagebox.showinfo("Setup Complete",
                    "QuickBMS installed successfully.\n\n"
                    "To extract game files, use 'Find Files' in the tuner\n"
                    "or re-run setup with a game root path.")
                return

            if not os.path.isdir(game_root):
                self._log(f"ERROR: Path does not exist: {game_root}")
                self.run_btn.configure(state=tk.NORMAL)
                return

            # Search for ZIPs
            self.progress_var.set("Searching for game ZIPs...")
            self._log(f"Searching {game_root} for tuning ZIPs...")
            et_zip = None
            ht_zip = None

            for dirpath, dirnames, filenames in os.walk(game_root):
                for fn in filenames:
                    if fn == "enginetuning.zip":
                        full = os.path.join(dirpath, fn)
                        if et_zip is None or "DVD1" in dirpath:
                            et_zip = full
                    elif fn == "harmonictuning.zip":
                        full = os.path.join(dirpath, fn)
                        if ht_zip is None or "DVD1" in dirpath:
                            ht_zip = full

            self.progress_bar["value"] = 55

            # Extract enginetuning.zip
            if et_zip:
                self._log(f"Found enginetuning.zip: {et_zip}")
                # Copy as backup
                backup_path = os.path.join(BASE_DIR, "enginetuning_backup.zip")
                if not os.path.isfile(backup_path):
                    shutil.copy2(et_zip, backup_path)
                    self._log("Created enginetuning_backup.zip")

                os.makedirs(ET_DIR, exist_ok=True)
                self.progress_var.set("Extracting enginetuning.zip (this may take a moment)...")
                self._log("Extracting enginetuning.zip with QuickBMS...")
                result = subprocess.run(
                    [QUICKBMS_EXE, ZIP_BMS, et_zip, ET_DIR],
                    capture_output=True, text=True, timeout=300)
                et_count = len([f for f in os.listdir(ET_DIR) if f.endswith(".xml")])
                self._log(f"Extracted {et_count} ET files")
            else:
                self._log("WARNING: enginetuning.zip not found in game root")

            self.progress_bar["value"] = 75

            # Extract harmonictuning.zip
            if ht_zip:
                self._log(f"Found harmonictuning.zip: {ht_zip}")
                os.makedirs(HT_DIR, exist_ok=True)
                self.progress_var.set("Extracting harmonictuning.zip...")
                self._log("Extracting harmonictuning.zip with QuickBMS...")
                result = subprocess.run(
                    [QUICKBMS_EXE, ZIP_BMS, ht_zip, HT_DIR],
                    capture_output=True, text=True, timeout=300)
                ht_count = len([f for f in os.listdir(HT_DIR) if f.endswith(".xml")])
                self._log(f"Extracted {ht_count} HT files")
            else:
                self._log("WARNING: harmonictuning.zip not found in game root")

            self.progress_bar["value"] = 100
            self.progress_var.set("Setup complete!")
            self.success = True

            et_count = len([f for f in os.listdir(ET_DIR) if f.endswith(".xml")]) if os.path.isdir(ET_DIR) else 0
            ht_count = len([f for f in os.listdir(HT_DIR) if f.endswith(".xml")]) if os.path.isdir(HT_DIR) else 0
            messagebox.showinfo("Setup Complete",
                f"Setup finished successfully!\n\n"
                f"Engine Tuning files: {et_count}\n"
                f"Harmonic Tuning files: {ht_count}\n\n"
                f"You can now close this window and launch the tuner.")

        except Exception as e:
            self._log(f"ERROR: {e}")
            self.progress_var.set("Setup failed")
            messagebox.showerror("Setup Error", str(e))

        self.run_btn.configure(state=tk.NORMAL)

    def run(self):
        self.root.mainloop()
        return self.success


def run_setup_gui():
    """Launch the setup GUI. Returns True if setup completed successfully."""
    win = SetupWindow()
    return win.run()


def run_setup_headless(game_root=None):
    """Run setup without GUI (for automation)."""
    results = []

    # Download QuickBMS
    if not os.path.isfile(QUICKBMS_EXE):
        print("Downloading QuickBMS...")
        try:
            req = urllib.request.Request(QUICKBMS_URL, headers={
                "User-Agent": "FM4CarAudioTuner-Setup/1.0"
            })
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            os.makedirs(QUICKBMS_DIR, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                zf.extractall(QUICKBMS_DIR)
            print("QuickBMS installed.")
            results.append("QuickBMS: installed")
        except Exception as e:
            print(f"Failed to download QuickBMS: {e}")
            results.append(f"QuickBMS: FAILED - {e}")
            return results

    # Create zip.bms
    if not os.path.isfile(ZIP_BMS):
        with open(ZIP_BMS, "w", newline="\n") as f:
            f.write(ZIP_BMS_CONTENT)
        results.append("zip.bms: created")

    if game_root and os.path.isdir(game_root):
        # Find and extract ZIPs (same logic as GUI)
        for dirpath, dirnames, filenames in os.walk(game_root):
            for fn in filenames:
                if fn == "enginetuning.zip":
                    et_zip = os.path.join(dirpath, fn)
                    os.makedirs(ET_DIR, exist_ok=True)
                    backup_path = os.path.join(BASE_DIR, "enginetuning_backup.zip")
                    if not os.path.isfile(backup_path):
                        shutil.copy2(et_zip, backup_path)
                    subprocess.run([QUICKBMS_EXE, ZIP_BMS, et_zip, ET_DIR],
                                   capture_output=True, timeout=300)
                    results.append(f"enginetuning: extracted")
                elif fn == "harmonictuning.zip":
                    ht_zip = os.path.join(dirpath, fn)
                    os.makedirs(HT_DIR, exist_ok=True)
                    subprocess.run([QUICKBMS_EXE, ZIP_BMS, ht_zip, HT_DIR],
                                   capture_output=True, timeout=300)
                    results.append(f"harmonictuning: extracted")

    return results


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--headless":
        game_root = sys.argv[2] if len(sys.argv) > 2 else None
        results = run_setup_headless(game_root)
        for r in results:
            print(r)
    else:
        run_setup_gui()
