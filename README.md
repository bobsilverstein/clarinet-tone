# Clarinet Tone Tracker

Records Bob's daily clarinet warm-up, measures the tone, and tracks which playing variables move it toward the sound his ear prefers.

## Get the app

1. Open the **Releases** page of this repository (right side of the main page).
2. Under the newest release, click **ClarinetTone.exe** to download it.
3. Double-click it.  Windows may warn about an unknown publisher: click **More info**, then **Run anyway**.

## What it does now (step 1)

1. Finds the Blue Snowball on its own and notes it in each recording's record.
2. Records mono, 48,000 Hz, 24-bit WAV.
3. Names each file from the date, start time, reed, and exercise.
4. Picks the long-tone exercise by odd or even day.
5. Shows a level meter with yellow and red warnings.
6. Pauses and resumes for interruptions.
7. Keeps a reed list; new reeds default to Vandoren 56 Rue Lepic, #3.
8. Saves to Documents\Claude\Clarinet tone\Recordings.

Each recording gets a matching `.json` file with the reed, exercise, tempo, microphone, pauses, and peak level.

## Still to come

Analysis and report after each exercise, recall of past reports, pitch meter, reed comparisons over time.
