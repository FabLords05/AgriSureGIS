# Antigravity CLI (`agy`) Installation Guide for Windows

This guide provides instructions on how to install, configure, and authenticate the Google Antigravity CLI (`agy`) on Windows systems.

---

## 1. Installation Methods

Open your terminal of choice (PowerShell is recommended) and execute the appropriate command:

### Option A: Using PowerShell (Recommended)
Open PowerShell (as a normal user, administrator privileges are not required) and run:
```powershell
irm https://antigravity.google/cli/install.ps1 | iex
```

### Option B: Using Command Prompt (CMD)
Open CMD and run:
```cmd
curl -fsSL https://antigravity.google/cli/install.cmd -o install.cmd && install.cmd && del install.cmd
```

---

## 2. Default Installation Path
The installer extracts the `agy` binary and adds it to your user environment path:
* **Binary Path:** `C:\Users\<Your-Username>\AppData\Local\agy\bin`
* **Configuration Directory:** `C:\Users\<Your-Username>\.gemini\antigravity-cli\`

---

## 3. Post-Installation Steps

### A. Launching the CLI
Once the script completes, restart your terminal and type:
```bash
agy
```

### B. First-Time Setup & Configuration
On your first run:
1. **TUI Setup:** The Terminal User Interface will load and guide you through basic setups (such as choosing color schemes and themes).
2. **Authentication:** The CLI will securely store session details in your Windows credential manager. If no active session is found, it will automatically open a browser window requesting you to log in to your Google Developer account.

---

## 4. Optional Installation Flags
If you need to customize the installation behavior, you can append the following flags to the installation command:
* `--skip-path`: Do not automatically append `agy` to your user PATH variable (requires manual configuration).
* `--skip-aliases`: Bypass modifications/purges of shell profiles.
