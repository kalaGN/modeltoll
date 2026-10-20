import test from "node:test";
import assert from "node:assert/strict";
import { fmtInt, fmtTime, fmtAmount, fmtMs } from "../../src/shared/lib/format.js";
test("formatting preserves UTC, decimal strings and missing values", () => {
 assert.equal(fmtInt(1000000), "1,000,000");
 assert.equal(fmtTime("2026-10-18T01:02:03"), "2026-10-18 01:02:03");
 assert.equal(fmtTime("2026-10-18T09:02:03+08:00"), "2026-10-18 01:02:03");
 assert.equal(fmtTime(null), "—"); assert.equal(fmtTime("invalid"), "invalid");
 assert.equal(fmtAmount("9007199254740993.000001"), "9007199254740993.000001");
 assert.equal(fmtAmount(null), "0.000000"); assert.equal(fmtMs(0), "0 ms"); assert.equal(fmtMs(null), "—");
});
