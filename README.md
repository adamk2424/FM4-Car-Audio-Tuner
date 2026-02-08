# FM4 Car Audio Tuner

A standalone Windows GUI tool for editing Forza Motorsport 4 engine audio tuning data. Modify engine sounds by changing which component is loaded for intake, engine or exhaust, adjusting audio DSP parameters, clone a car's engine to sound like another, and manage game file changes with backup restoring.

Built for use with Xbox 360 disc dumps and the Xenia emulator.

## Quick Start

1. Download the latest release (or build from source)
2. Place `FM4_CarAudioTuner.exe` in its own folder
3. Launch the exe - first-run setup will download QuickBMS and guide you through locating your game files
4. Select a car, tweak audio parameters, save, and export back to your game
5. Fastest way to hear changes is to the car into Test Drive (or any track) and drive it. You can push changes, back out and reload the car on track and it will load the updated audio banks. Audio does not reload while driving, only at track/car load time.

## First-Run Setup

On first launch, the tool detects missing components and opens the setup wizard. It will:

- **Download QuickBMS** - Required for handling Xbox 360's proprietary ZIP compression (method 21 / XMemCompress). Standard tools like 7-Zip cannot read these files.
- **Create the zip.bms script** - The extraction script QuickBMS needs.
- **Locate and extract game ZIPs** - Point it at your FM4 game root (e.g. `C:\Emulators\FM4Plus\`) and it will find `enginetuning.zip` and `harmonictuning.zip`, extract all car XMLs, and create a backup of the original ZIP.
- **Install audioengineconfig.xml** - Copies a patched audio engine config into your game's audio folder (see below).
- **Install reflections.fev** - Copies a tuned vehicle reflections audio file into the game's Reflections folder for improved in-car sound reflections.

You can also run setup manually:
```
python setup_fm4tuner.py
```

Or headless:
```
python setup_fm4tuner.py --headless C:\path\to\game\root
```

## Features

### Find Files (DLC Support)
Click **Find Files** and select your game root directory and the tool will automatically:
- Discover DLC engine tuning and harmonic tuning XMLs scattered across content folders
- Copy them into local working directories (`dlc_enginetuning/`, `dlc_harmonictuning/`)
- Build a file mapping (`file_mapping.json`) so Export knows where to write files back
- The mapping indicator dot turns green when file mapping is active

### Car Browser
- Search and filter cars by name
- Car list shows all available Engine Tuning (ET) XMLs from both the main game and DLC packs
- Cylinder type auto-detects from the car's exhaust component

### Audio Parameter Editing
Each car has three audio components that make up the engine sound. Each as their own tab (**Intake**, **Engine**, **Exhaust**) for their behavior controls (Volume and Peak EQ and Lowpass filter, more on exhaust) plus a **Global Effects** tab. General advice: Intakes should usually only be heard when on throttle and silent when off; Exhausts should have an on/off throttle effect for positive and negative load to sound like a working engine.

### *IMPORTANT* When selecting components, do not map engine types that do not match together or it will sound bad/fake. This means you can mix and match sounds as long as they are part of the same harmonic groups based on cyclinder count. Those groups are:
- 2,4,8,16
- 3,6,12
- 5,10
- Rotary

**Per-component controls:**
- **Volume** - Gain curve with Active toggle (muting zeroes the curve; real values are preserved in a sidecar file)
- **PEQ** (Parametric EQ) - Gain, Center Frequency, Bandwidth
- **Lowpass** - Cutoff Frequency, Resonance
- **Expander** (Exhaust only) - MaxGain, Attack/Hold/Release times
- **Load PEQ** (Exhaust only) - Positive and Negative load parametric EQ

**Global effects:**
- **FocusPEQ** - Global parametric EQ applied to entire sound of the car.
- **Distortion** - Adds intensity through distortion, but sounds crackly/clippy when pushed far. Includes bands and volume compensation
- **Compressor** - Threshold, Attack, Release, GainMakeup
- **ShiftVolumeScalar** - Gear shift volume boost parameters
- **TrashDSP** - 3-band distortion/saturation with per-band curves. Distortion Type has 0, 1, 2 for different algorythms. 2 generally sound the most intense. 

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

### Save and Export
- **Save** - Writes changes to the local XML file (in the working directory)
- **Export** - Repackages the main game ZIP using QuickBMS reimport, rebuilds the ZIP central directory, copies DLC files to their mapped game locations
- **Output Location Override** - Optionally redirect all exported files to a specific folder instead of the mapped game paths

### Backup and Restore
- **Backup** - Copies your current game files (main ZIPs + DLC XMLs) to `<game_root>/backups/default/`. If a backup already exists, you can overwrite it or create a named backup.
- **Restore Backup** - Select a backup to restore. Copies files back to their original game locations and updates local working directories.

### Undo / Redo
- **Ctrl+Z** / **Ctrl+Y** - Up to 50 levels of undo/redo for all parameter changes

## Audio Engine Config (audioengineconfig.xml)

During setup, the tool installs a patched `audioengineconfig.xml` into your game's audio directory. This file controls the game's global audio mix and mastering settings. The included version changes the following values from the stock defaults:

| Setting | Stock | Patched | Effect |
|---------|-------|---------|--------|
| `gamePlayerEngine` | 1.0 | 0.5 | Reduces player engine volume in the mix |
| `gameCarWind` | 0.8 | 0.4 | Reduces wind noise |
| `gameTire` | 1.0 | 1.3 | Boosts tire audio for better road feel |
| `gameCollision` | 1.0 | 0.5 | Softens collision sounds |
| `saturatorLevel` | 0.95 | 0.6 | **Key change** - reduces global saturation |

The `saturatorLevel` was shipped at 0.95, which led to a lot of that crunchy/distorted sound that went too far. Setting it to 0.6 will make the game a bit quieter overall, and maybe a little less intense, but it cleans up a lot of that over-the-top distortion, so it's worth setting as a new default for all cars. Some cars are still very crunchy, but you can fix those by turning down their distortion overdrive on a per-engine basis using this tool.

## File Structure

```
FM4CarAudioTuner/
  FM4_CarAudioTuner.exe          # Main application
  FM4_CarAudioTuner.py           # Source code
  setup_fm4tuner.py              # First-run setup script
  audioengineconfig.xml          # Patched game audio mix config (installed by setup)
  reflections.fev                # Tuned vehicle reflections audio (installed by setup)
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
