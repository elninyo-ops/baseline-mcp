# Snow routing test: run status (2026-11-12)

**Complete. Pre-registered result: FAIL on one question (S11).**
- 10 of 11 snow questions pass: S01 to S10 went to `get_climate_context` in 9 of 9 runs.
- All 9 controls pass, each going to the same tool as on the live descriptions, 9 of 9.
- The original trigger test passes under E.
- S11 (a snow *forecast* against normal) fails. See "S11" below.

## Setup
- **Design:** `../snow_routing_test_2026-11-12.json`. It was committed before any API call, in `d8ee95c`.
- **Amendment 1:** made after the live (D) run and before any E call, in `36d4b1f`. E also edits `compare_locations`. The reason is in the amendment.
- **Versions.**
  - D is live: 8c174b1's descriptions. They were checked byte for byte, schemas included.
  - E is new. It changes four descriptions: `get_climate_context`, `get_water_year_status`, `compare_to_normal` and `compare_locations`.
  - Both versions include the `get_weather_forecast` distractor, as in the earlier trigger tests.
- **Harness:** `harness/run_addendum.py`, copied unchanged from `hoodoo-trigger-test-2026-11-03`.
  - Models: Sonnet, Opus and Haiku 5.5, 3 runs each, so 9 runs per question.
  - No system prompt, `max_tokens` 1024, and anthropic 0.109.2.
  - The key variable is `BASELINE_TEST_ANTHROPIC_KEY`.
- **Errors:** none. Every question has 9 runs under each version, and the harness printed no STOP or GAVE UP lines.

## Snow and control questions (first tool, 9 runs)
| id | question | D (live) | E (new) | E |
|---|---|---|---|---|
| S01 | How much snow has Denver had so far this season? | compare_locations 9 | get_climate_context 9 | PASS |
| S02 | How much snow has fallen in Sapporo so far this winter? | compare_locations 9 | get_climate_context 9 | PASS |
| S03 | Is Montreal snowier than usual so far this winter? | compare_locations 8, water_year 1 | get_climate_context 9 | PASS |
| S04 | What's Calgary's snowfall total for the season to date? | compare_locations 9 | get_climate_context 9 | PASS |
| S05 | How snowy was last winter in Queenstown, New Zealand? | climate_context 6, compare_locations 3 | get_climate_context 9 | PASS |
| S06 | Did Thredbo get a good snow season this year? | climate_context 6, water_year 2, compare_locations 1 | get_climate_context 9 | PASS |
| S07 | Has Innsbruck had much snow yet this season? | compare_locations 9 | get_climate_context 9 | PASS |
| S08 | How did last winter's snowfall in Oslo compare with normal? | compare_locations 6, climate_context 3 | get_climate_context 9 | PASS |
| S09 | Was the 2024-25 winter a snowy one in Chamonix? | compare_locations 8, climate_context 1 | get_climate_context 9 | PASS |
| S10 | How much snow has fallen at 43.06, 141.35 since the snow season started? | compare_locations 8, water_year 1 | get_climate_context 9 | PASS |
| S11 | Is Calgary going to get more snow than normal over the next week? | compare_to_normal 8, weather 1 | weather 6, climate_context 2, compare_to_normal 1 | **FAIL** |
| C01 | How much rain has Fresno had this water year compared to normal? | water_year 9 | water_year 9 | PASS |
| C02 | Is Casper, Wyoming in drought this water year? | water_year 9 | water_year 9 | PASS |
| C03 | Will Denver be warmer than normal over the next 10 days? | compare_to_normal 9 | compare_to_normal 9 | PASS |
| C04 | What's the 10-day forecast for Madrid? | weather 9 | weather 9 | PASS |
| C05 | Will the coming season be warmer than normal in Nairobi? | seasonal_outlook 9 | seasonal_outlook 9 | PASS |
| C06 | Compare this water year's rainfall in Fresno and Sacramento. | compare_locations 9 | compare_locations 9 | PASS |
| C07 | Which has had more snow this ski season, Vail or Park City? | compare_locations 9 | compare_locations 9 | PASS |
| C08 | What do the next 10 days look like at 41.14, -104.82 compared with normal? | coordinates 9 | coordinates 9 | PASS |
| C09 | How did August 2026 rank for heat in Phoenix? | climate_context 9 | climate_context 9 | PASS |

**What the live run showed.** Live sent most snow questions to `compare_locations`, the only description that says "snowfall".
- In the 99 snow runs, `compare_locations` was the first tool 70 times.
- To fit that tool, the model made up places. For example, "Denver" became ["Denver, CO", "Boulder, CO"], snowfall, ski_season.
- `get_water_year_status`, the tool from the owner's session, came first in 4 runs. It was also the second call in several runs.
- When live did reach `get_climate_context`, it often asked a rain question, such as "How wet was last winter in Thredbo?".

**S11.**
- On S11, E moved the model away from `compare_to_normal`, which can't do snow. But it mostly went to the generic forecast tool, not to `get_climate_context`.
- The API ranks forecast temperature and precipitation against normal, but it gives forecast snow only as an amount (`forecast_snow.py`). No Hoodoo tool answers "more snow than normal next week".
- So S11 had no fully right tool. Putting it in the "must be get_climate_context" set was a design error, made when the test was written. The result is reported as a FAIL anyway.

## Original trigger test under E (29 questions, 9 runs each)
- **PASS.** Every scored question meets its criterion, with the same counts as D:
  - triggers: 9/9 Hoodoo first;
  - misfires: 0/9;
  - forecasts: 9/9 weather first;
  - everyday "who do": 0/9.
- Dictation questions (report only): D01 6/9, D02 9/9, D03 9/9, D04 7/9, the same as D.
- **T04 "hoodoo snow Calgary"** was already this bug in the old test. D sent it to `get_water_year_status` 7 times out of 9. E sends it to `get_climate_context` 9 out of 9.
- **The first Hoodoo tool for a bare place changed.** "hoodoo Casper" (T09) went to `get_water_year_status` 9/9 under D. Under E, it goes to `get_climate_context` 4 and `get_water_year_status` 5.
  - In those `get_climate_context` runs, the model asks "Will Casper be warmer than normal this week?". It also calls `get_water_year_status` in the same response, so the water year is still reported.
  - "hoodoo Tokyo this winter" (T03) went to `get_seasonal_outlook` 9/9 under D. Under E, it goes to `get_seasonal_outlook` 6 and `get_climate_context` 3, where the question asked is "Will this winter be warmer than normal in Tokyo?".

## Cost
- 621 calls in all, $9.54, with a cap of $15:
  - snow test D: $2.56;
  - snow test E: $2.43;
  - trigger rerun E: $4.55.

## Files
- `version_D.json`, `version_E.json`: the tool lists that were sent to the model.
- `results_snow_D.jsonl`, `results_snow_E.jsonl`, `results_trigger_E.jsonl`: one line per call.
- `results_summary_snow.json`, `results_summary_trigger_E.json`: the scorers' output.
- `score_snow.py`, `score_trigger_E.py`: the scorers, both committed before the runs.
