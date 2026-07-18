# LTG on Windows — Install & Play Guide

Everything installs into one folder. You'll do steps 1–3 exactly once; after
that it's just double-clicking a launcher.

---

## 1. One-time setup

### a. Install Python

1. Go to <https://www.python.org/downloads/> and click the big yellow
   **Download Python** button.
2. Run the installer. On the FIRST screen, **tick the box that says
   "Add python.exe to PATH"** (bottom of the window) — this matters.
3. Click **Install Now** and let it finish.

### b. Install Git

1. Go to <https://git-scm.com/download/win> — the download starts
   automatically.
2. Run the installer. Every default is fine — just keep clicking **Next**,
   then **Install**.

### c. Download the game

1. Open **File Explorer** and go to the folder you want the game to live in
   (for example **Documents**).
2. Click in the address bar at the top, type `cmd`, and press **Enter** — a
   black command window opens in that folder.
3. Copy-paste this line into it and press **Enter**:

   ```
   git clone https://github.com/LocalCalzoneZone/LTG.git
   ```

   A folder called **LTG** appears with the whole game inside.

> **Don't use GitHub's "Download ZIP" button instead** — a ZIP copy can't
> receive updates. The `git clone` above is what makes the Update button work.

---

## 2. Starting the game

Inside the **LTG** folder:

| Double-click | To get |
|---|---|
| **LTG-Game.bat** | The game itself |
| **LTG-Deckbuilder.bat** | The character / deck editor |

- The **first** launch sets everything up and takes a few minutes — that's
  normal. After that it's seconds.
- A black window opens and stays open — **that window IS the app**. Your
  browser then opens the game by itself. Closing the black window stops the
  app.
- If Windows Firewall asks whether to allow it: click **Allow**.
- If the browser doesn't open on its own: the game is at
  <http://localhost:8020>, the deckbuilder at <http://localhost:8000>.

**Quitting:** in the game, use **Options → Settings → Quit LTG**. In the
deckbuilder, use the **Quit** button in the top bar. Both stop the app
completely (the black window closes too), so nothing keeps running in the
background.

---

## 3. Characters

Characters are `.json` files. They live only on your computer — updates never
touch them — and they're small enough to send over any chat.

### Play a character someone sent you

1. Save the `.json` file somewhere you can find it (e.g. Documents).
2. Start **LTG-Game** → **Options → Characters** → **Import** → pick the file.
3. It's now in your roster for any New Game.

### Edit a character (the good path)

1. Start **both** apps: LTG-Game and LTG-Deckbuilder.
2. In the game: **Options → Characters** → find the character → **Edit**.
   The deckbuilder opens with that character loaded.
3. Make your changes (cards, stats, portrait…).
4. Click **Update Game Character** (top right). Done — the game uses the new
   version from the next New Game onward.

### Send a character to someone

1. Open the character in the **Deckbuilder** (via the Edit path above, or its
   **Load** button and picking a `.json` file).
2. Click **Save** in the top bar and choose where to put the `.json` file.
3. Send that file (email, chat, whatever). They import it with the
   **Import** button in their game.

---

## 4. Updating the game

When there's a new version:

1. Start **LTG-Game** → **Options → Settings** → **Updates**.
2. If it says updates are available, click **Update now** and wait — it can
   take a minute.
3. **Quit** (same Settings page) and relaunch. That's it — one update covers
   the game, the deckbuilder, and any new encounters or adventures.

Your saved characters are never touched by an update.

---

## 5. If something goes wrong

- **The launcher window flashes an error about Python** — Python probably
  isn't on PATH. Re-run the Python installer, tick **Add python.exe to
  PATH**, then delete the `.venv` folder inside LTG and double-click the
  launcher again.
- **An update said "delete the .venv folder"** — do exactly that: close the
  app, delete the folder called `.venv` inside LTG, and double-click the
  launcher. It rebuilds itself.
- **The game page won't load** — check the black window is still open, then
  try <http://localhost:8020> in your browser.
- **Anything else** — screenshot the black window and send it to your game
  admin.
