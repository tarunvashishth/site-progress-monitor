import { describe, expect, it } from "vitest";
import { packageErrors } from "@/components/package-editor";
import { validateVideoFile, weightsTotal } from "@/lib/validation";

const MB = 1024 * 1024;
describe("upload validation", () => {
  it("accepts mp4 and mov", () => {
    expect(validateVideoFile({ name: "a.MP4", size: MB, type: "video/mp4" })).toBeNull();
    expect(validateVideoFile({ name: "a.mov", size: MB, type: "video/quicktime" })).toBeNull();
  });
  it("rejects wrong type, mismatched mime, empty and oversize files", () => {
    expect(validateVideoFile({ name: "a.avi", size: MB, type: "video/x-msvideo" })).toMatch(/MP4 and MOV/);
    expect(validateVideoFile({ name: "a.mp4", size: MB, type: "application/pdf" })).toMatch(/does not match/);
    expect(validateVideoFile({ name: "a.mp4", size: 0, type: "video/mp4" })).toMatch(/empty/);
    expect(validateVideoFile({ name: "a.mp4", size: 11 * MB, type: "video/mp4" }, 10 * MB)).toMatch(/exceeds/);
    expect(validateVideoFile({ name: "noext", size: MB, type: "" })).not.toBeNull();
  });
});

describe("work package validation", () => {
  const row = (name: string, w: string, p = "0") => ({ name, weight_percentage: w, initial_approved_percentage: p });
  it("sums weights without float drift", () => expect(weightsTotal([row("a", "33.3"), row("b", "33.3"), row("c", "33.4")])).toBe(100));
  it("requires exactly 100, baselines, unique names", () => {
    expect(packageErrors([row("A", "60"), row("B", "40")])).toBeNull();
    expect(packageErrors([row("A", "60"), row("B", "30")])).toMatch(/exactly 100/);
    expect(packageErrors([row("A", "100", "")])).toMatch(/starting completion/);
    expect(packageErrors([row("A", "50"), row("a", "50")])).toMatch(/unique/);
    expect(packageErrors([])).toMatch(/at least one/);
  });
});
