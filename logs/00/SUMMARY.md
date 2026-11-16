# Test set 00: summary

Hand-written, because the logs of this set predate [LOGGING.md](../../LOGGING.md) and `summarize.py` cannot read them. This set is **not** used for the report. Numbers are copied from the root summaries (`root/*/root_summary_*.txt`) and the node summaries / logs that exist.

Setup of the run: root + 9 sources (nodes 1, 3, 4, 5, 6, 7, 8, 10, 12), 30 s warm-up, 300 s measured run, 30 s drain, one sample every ~10 s per node (about 29 to 30 samples each). Transmit power 0.25 to 1.5 dBm, changing between attempts. Scenario: stable topology only, no relay was switched off.

## Did it work?

**Flooding: yes.** The root received nearly everything, and all three runs are alike.

**DV: partly.** Routes formed, multi-hop forwarding worked and packets reached the root over up to 4 hops. But delivery was clearly worse than flooding and the routes never settled.

| run | mode | PDR at root (root's estimate) | sources heard at root | notes |
| --- | --- | --- | --- | --- |
| 1 | flood | 261/265 = 98.5% | 9 of 9 | node 4, 7, 8, 12 lost 1 packet each |
| 2 | flood | 231/236 = 97.9% | 8 of 9 | node 10 never delivered (its link is the weakest in the other runs, -91 to -93 dBm) |
| 3 | flood | 254/259 = 98.1% | 9 of 9 | node 12: 23 delivered, nothing after seq 22, so the tail was probably lost and the real PDR is about 77% (the estimate cannot see it) |
| 1 | dv | not in a file of its own | | see [Missing runs](#missing-runs) |
| 2 | dv | 143/202 = 70.8% | 7 of 9 | **nodes 5 and 6 never heard**, root dropped 104 packets for a wrong run ID |
| 3 | dv | 216/264 = 81.8% | 9 of 9 | |
| 4 | dv | 224/264 = 84.8% | 9 of 9 | |

Flooding delivered about 98%, DV 71 to 85% in this set. PDR denominators are the root's estimate (highest sequence number seen + 1), so they are slightly optimistic; the exact ones need every node's `generated` count.

### Flooding

- Delivery is uniform across sources: 93 to 100% per source in every run.
- It is expensive. The root dropped 1459 to 1781 duplicates for 231 to 261 unique packets, so about 6 to 7 copies of each packet arrive. Node 5 sent 231 to 259 packets per run (29 own + 202 to 230 relayed, no adverts). Team 7 (node 7) sent 29 own + 195 to 229 relayed and dropped 1181 to 1468 duplicates.
- Sources were first heard late (24 to 59 s after the root boot) because flooding has no adverts; this is the first data packet, and the first sample is generated at 30 s.

### DV

- Forming routes is fast: every node was heard 2 to 9 s after the root boot and had a route within about 7 to 19 s, except node 8 in run 3 (heard at 40 s, route at 45 s).
- Hop counts: run 2 had everyone at hop 2 via node 3 except node 3 (hop 1). Run 3 reached hop 3, run 4 hop 4 (nodes 7 and 12 via node 8).
- **Routes did not settle.** In all three runs most nodes were still changing route near the end: the last change was between 282 and 360 s for 22 of the 25 node-runs, mostly the parent switching between neighbours. The root saw roughly 100 to 180 route changes per run after the warm-up. The root's own `CONVERGE` message (all nodes have a route, nobody changed for 15 s) fired in run 4 at 40 s and in run 2 only at 347 s (7 nodes), and never in run 3. Re-evaluating the same rule on the logged route changes gives 51, 45 and 40 s for runs 2, 3 and 4: a short quiet window early on, which the root's 10 s check can miss, followed by constant changes (run 4 changed again at 132, 159 and 245 s). So the first-convergence number looks fine, but the routes are not stable afterwards.
- Several links sit at or below the RSS threshold of -85 dBm (node 10: -84 to -91 dBm, node 4: -86 to -88, node 3: -82 to -90, node 12: -83 to -88). These are the sources with the lowest DV PDR (node 10: 57 to 76%, node 12: 55 to 77%, node 4: 64 to 83%, node 3: 62 to 93%), and the first to flap.
- Overhead on the nodes that have counters: node 5 sent 101 (run 4, relayed only 4) and 207 (run 3, relayed 110) packets per run in DV, of which 68 are adverts. In flooding it sent 231 to 259. Total network overhead cannot be computed: only node 5 has a node summary.
- Team 7 (node 7, GPS) DV logs: 21 to 41 parent changes per run (the node kept moving between nodes 1, 3, 6, 8, 12), `neighbor_expired` 13 to 19, and in run 2 `no_route_drops=8` and `bad_packet=106`.

### Problems in the data

- **DV run 2 had a run ID mismatch.** The root's summary shows `run=104` dropped packets, and Team 7's node counted `bad_packet=106`. Nodes 5 and 6 never show up in the root's route table or deliveries. This fits boards still on a different `RUN_ID`, and it also explains why node 5 has no summary for DV run 2 (the node files are named by `RUN_ID`). Inferred from the counters, not confirmed on the boards.
- Per-source PDR above 100% (node 8, DV run 2: 29 delivered, highest seq + 1 = 28) means that node's sequence numbers repeated, most likely a reboot mid-run. The root-side estimate breaks then. The exact denominator from the node summary avoids this.
- Root log files contain several restarts and aborted attempts one after another (`root started` lines), because the log was appended and `RUN_ID` was not increased. The summary file of a run is correct, the log is not one run. The new code opens the events file with `"w"` at boot.

## Missing runs

- **DV run 1**: no `root_*_dv_run1` files exist, but the root wrote its DV run 1 attempts into `root/flood/root_log_flood_run1.txt` (the old code did not put the mode in the file name): the blocks that end at the `SUMMARY` lines 890 (1.0 dBm, 149/177 = 84.2%) and 1456 (0.5 dBm, 93/189 = 49.2%). Both are from an older node set (node 9 present, node 5 absent) and mixed power settings, so they are not comparable with runs 2 to 4. Both only have the root side.
- **Node 5, DV run 2**: no summary (see the run ID mismatch above).
- Only node 5 (CO, our team) and node 7 (Team 7, GPS) have node-side logs; all other teams' files are missing, so the overhead cannot be computed for any whole run.

## What to fix before the real runs

1. Everyone uses [LOGGING.md](../../LOGGING.md); check `RUN_ID` and `MODE` on every board before every run, and use a new `RUN_ID` per attempt.
2. Same node set in every run (nodes 5 and 6 were missing in DV run 2).
3. Move the weakest sources (node 10, node 12) closer or accept that they lose packets in both protocols.
4. Decide the failure-scenario relay and timing before the runs, and set the same `SCENARIO`, `FAILED_NODE`, `FAIL_AT_S` on every board (the relay switches itself off in software, see [LOGGING.md](../../LOGGING.md#failure-scenario)).
