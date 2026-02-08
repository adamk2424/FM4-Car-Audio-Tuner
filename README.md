# FM4 Car Audio Tuner

A standalone Windows GUI tool for editing Forza Motorsport 4 engine audio tuning data. Modify engine sounds by adjusting audio DSP parameters, swap audio profiles between cars, and manage game file backups.

Built for use with Xbox 360 disc dumps and the Xenia emulator.

## Quick Start

1. Download the latest release (or build from source)
2. Place `FM4_CarAudioTuner.exe` in its own folder
3. Launch the exe - first-run setup will download QuickBMS and guide you through locating your game files
4. Select a car, tweak audio parameters, save, and export back to your game

## First-Run Setup

On first launch, the tool detects missing components and opens the setup wizard. It will:

- **Download QuickBMS** - Required for handling Xbox 360's proprietary ZIP compression (method 21 / XMemCompress). Standard tools like 7-Zip cannot read these files.
- **Create the zip.bms script** - The extraction script QuickBMS needs.
- **Locate and extract game ZIPs** - Point it at your FM4 game root (e.g. `C:\Emulators\FM4Plus\`) and it will find `enginetuning.zip` and `harmonictuning.zip`, extract all car XMLs, and create a backup of the original ZIP.

You can also run setup manually:
```
python setup_fm4tuner.py
```

Or headless:
```
python setup_fm4tuner.py --headless C:\path\to\game\root
```

## Features

### Car Browser
- Search and filter 500+ cars by name
- Car list shows all available Engine Tuning (ET) XMLs from both the main game and DLC packs
- Cylinder type auto-detects from the car's exhaust component

### Audio Parameter Editing
Each car has three audio component tabs (**Intake**, **Engine**, **Exhaust**) plus a **Global Effects** tab.

**Per-component controls:**
- **Volume** - Gain curve with Active toggle (muting zeroes the curve; real values are preserved in a sidecar file)
- **PEQ** (Parametric EQ) - Gain, Center Frequency, Bandwidth
- **Lowpass** - Cutoff Frequency, Resonance
- **Expander** (Exhaust only) - MaxGain, Attack/Hold/Release times
- **Load PEQ** (Exhaust only) - Positive and Negative load parametric EQ

**Global effects:**
- **FocusPEQ** - Global parametric EQ
- **Distortion** - Level curve with volume compensation
- **Compressor** - Threshold, Attack, Release, GainMakeup
- **ShiftVolumeScalar** - Gear shift volume boost parameters
- **TrashDSP** - 3-band distortion/saturation with per-band curves

Each parameter has:
- **PhysicsCoeff sliders** - RPM, Throttle, PosTorque, NegTorque (constrained to sum <= 1.0)
- **ThreePointCurve editor** - Visual canvas with 3 draggable control points plus numeric entry fields

### Clone Audio
Copy all audio settings from one car to another:

1. Select a car in the left car list (this is the **target** - the car whose file will be modified)
2. Check **Enable Clone** in the Clone Audio panel on the right
3. Search and select a **source** car in the clone list
4. All audio parameters, component selections, and redline populate from the source car
5. Click **Save** - the target car's file is written with the source car's audio settings
6. Uncheck **Enable Clone** to restore the target car's original settings

### Find Files (DLC Support)
Click **Find Files** and select your game root directory to:
- Discover DLC engine tuning and harmonic tuning XMLs scattered across content folders
- Copy them into local working directories (`dlc_enginetuning/`, `dlc_harmonictuning/`)
- Build a file mapping (`file_mapping.json`) so Export knows where to write files back
- The mapping indicator dot turns green when file mapping is active

### Save and Export
- **Save** - Writes changes to the local XML file (in the working directory)
- **Export** - Repackages the main game ZIP using QuickBMS reimport, rebuilds the ZIP central directory, copies DLC files to their mapped game locations
- **Output Location Override** - Optionally redirect all exported files to a specific folder instead of the mapped game paths

### Backup and Restore
- **Backup** - Copies your current game files (main ZIPs + DLC XMLs) to `<game_root>/backups/default/`. If a backup already exists, you can overwrite it or create a named backup.
- **Restore Backup** - Select a backup to restore. Copies files back to their original game locations and updates local working directories.

### Undo / Redo
- **Ctrl+Z** / **Ctrl+Y** - Up to 50 levels of undo/redo for all parameter changes

## File Structure

```
FM4CarAudioTuner/
  FM4_CarAudioTuner.exe          # Main application
  FM4_CarAudioTuner.py           # Source code
  setup_fm4tuner.py              # First-run setup script
  zip.bms                        # QuickBMS extraction script (created by setup)
  quickbms/
    quickbms.exe                 # Xbox 360 ZIP handler (downloaded by setup)
  enginetuning_extracted/        # Main game car XMLs (created by setup)
  harmonictuning_extracted/      # Main game HT component XMLs (created by setup)
  dlc_enginetuning/              # DLC car XMLs (created by Find Files)
  dlc_harmonictuning/            # DLC HT XMLs (created by Find Files)
  enginetuning_backup.zip        # Original game ZIP backup (created by setup)
  file_mapping.json              # DLC file path mapping (created by Find Files)
```

## Building from Source

Requires Python 3.10+ with tkinter (included with standard Python on Windows).

No additional pip packages are needed - the tool uses only the standard library.

**Build the exe:**
```
pip install pyinstaller
pyinstaller --onefile --windowed --name FM4_CarAudioTuner FM4_CarAudioTuner.py
```

## Important Notes

- **Always keep a backup** of your original `enginetuning.zip` before exporting. The setup script creates one automatically as `enginetuning_backup.zip`.
- **Export rebuilds from the backup ZIP** each time - it copies the backup, reimports modified XMLs, then rebuilds the central directory. Never delete `enginetuning_backup.zip`.
- The tool handles Xbox 360's proprietary compression (method 21) through QuickBMS. Standard ZIP tools will corrupt these files.
- Volume muting works by zeroing curve values in the XML while preserving real values in a `.volstate.json` sidecar file.
