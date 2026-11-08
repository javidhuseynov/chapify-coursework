# Chapify Print Station

The program that runs next to a printer. It is a **separate application** from the Chapify web
server: it has its own process and no access to Chapify's database. It uses only the Python
standard library (the window uses tkinter, which is part of standard Python on Windows).

```
Chapify server                                   Print station (this program)
--------------                                   ----------------------------
                       POST /api/printer/heartbeat/          every 10 s: status, paper, toner
                       POST /api/printer/jobs/next/          take the next paid job
                       GET  /api/printer/jobs/<id>/document/ download the PDF (checked with SHA-256)
                                                             "print" it on the simulated printer
                       POST /api/printer/jobs/<id>/complete/ or  .../fail/  {"reason": ...}
```

Every request carries the printer's **station key**: `Authorization: Printer <key>`.

## Start it (Command Prompt, in the Chapify folder)

1. In Chapify, log in as an administrator, open **Printers** and press **Connect a print station**
   next to a printer. Copy the key (it is shown only once).
2. Start the station (the Chapify server must be running):

   ```bat
   set CHAPIFY_STATION_KEY=<paste the key>
   python -m print_station --server http://127.0.0.1:8000
   ```

   Using the variable keeps the key out of the command history; `--key <key>` also works.

The window shows the printer, the connection to Chapify, the job being printed with a progress
bar, paper and toner levels, and an activity log. Buttons: **Switch off/on**, **Load paper**,
**Replace toner**, **Clear jam**, and **Jam the next job** for demonstrating a failure.

| Option | Meaning |
|---|---|
| `--headless` | No window; log to the console |
| `--once` | Print everything that is waiting, then exit |
| `--seconds-per-page 0.5` | Printing speed |
| `--jam-rate 0.1` | Probability that a job jams |
| `--paper 500`, `--toner 100` | Starting paper (sheets) and toner (%) |
| `--receipts <folder>` | Where job receipts are written (default `print_station_receipts`) |

## Behaviour worth knowing

- **Status.** Chapify keeps the printer *Offline* until the station's first heartbeat. Switched
  off → *Offline*; jam, no paper or no toner → *Error*. Only *Available* printers receive jobs.
- **Failures.** A jam, too little paper or toner for the job, or a damaged download fails the job
  with that reason. Chapify keeps the document so an administrator can use **Print again**.
- **Station stops.** If no heartbeat arrives for 60 s (`CHAPIFY_PRINT_STATION_TIMEOUT_SECONDS`),
  Chapify marks the printer *Offline* and fails the job it was printing. A restarted station first
  gets back the job it was printing.
- **Privacy.** The document is held in memory only while it prints and is never written to disk.
  Receipts contain job details (owner, file name, settings, result), not the document.
- **Security.** The key works only for the printer API and only for its own printer's jobs; a
  station cannot see other printers' documents or any user data beyond the job it prints. Chapify
  stores only the key's SHA-256 hash; **New station key** replaces it, **Disconnect** removes it.
  Use `https://` for any server that is not on the same computer.

## Tests

`print_station/tests/` tests the simulated printer on its own;
`printing/tests/test_print_station.py` tests the printer API and runs this program against a live
Chapify test server.
