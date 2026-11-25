# Roadmap

- [x] Al Kamel Analysis CSV parser, validated on the full 2026 Le Mans Cup season
- [x] Live engine: net order, drive-time watch, caution calls, radio feed (time-safe)
- [x] Rules learned from earlier rounds (stops, window, stop cost by flag)
- [x] Post-race debrief and a real-data case study
- [x] AI race engineer: claude.ai pit wall (tools, voice) and MCP server
- [x] Stint / tyre / driver planner (exact DP, brute-force tested)
- [x] JavaScript engine with parity tests against Python on real races
- [x] Accuracy benchmark on 56 real races with targets ([ACCURACY.md](ACCURACY.md))
- [x] Official classification: minimum drive time, driver categories, penalty check
- [x] Calibrated caution calls, conformal ranges, number check on AI answers
- [ ] Live mode: read the championship's live timing feed during a race weekend
- [ ] Opponent stop prediction from each rival's earlier stints and the window
- [ ] Rolling drive-time windows and driver categories from the Sporting Regulations
- [ ] Monte Carlo of caution risk on top of the deterministic plan
- [x] Validate on ELMS seasons (4 h races, fuel-limited stops)
- [ ] Asian Le Mans Series and IMSA
- [ ] Pilot with a team on a race weekend
