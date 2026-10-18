# Back up and restore Olfy data

Open **Lab → Dataset → Full data backup**, or **consumer Settings → Back up recordings**. Finish or abort any active recording first. The download includes:

- Real and simulation recordings, including interrupted and aborted scans.
- The 50-perfume catalogue, measured curves, features and sensor definitions.
- Saved collection bookmarks.
- Current model files and preserved training-run history.
- A manifest with file checksums and record counts.

The backup uses SQLite's backup API, including committed WAL contents. A second Olfy process cannot open the same data folder and silently reset an active scan.

## Restore to a new folder

Stop Olfy. From the project folder:

```bash
bash start.sh --restore-backup ~/Downloads/Olfy_Data_Backup.zip --data-dir ./data-recovered
bash start.sh --data-dir ./data-recovered
```

Choose an empty/new folder. Restore verifies checksums, supported filenames and database integrity before writing. It refuses to overwrite an existing dataset. Your original `data/` is preserved.

For a command-line backup while Olfy is stopped:

```bash
bash start.sh --backup-to ~/Downloads/Olfy_Backup_01.zip
```

Choose a new filename; the command does not overwrite an existing backup. The archive holds data, not the app source. Keep `Olfy_Starter.zip` as well. Standalone HTML design-preview session bookmarks are not measurements and are not part of a data backup.
