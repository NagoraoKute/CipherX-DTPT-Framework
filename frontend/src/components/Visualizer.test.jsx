import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Visualizer, { massBeyond } from "./Visualizer.jsx";

// Discretised binomial-like curves: honest around 3%, forged around 50%.
const bump = (center, spread, x) => Math.exp(-((x - center) ** 2) / (2 * spread ** 2));
const grid = Array.from({ length: 121 }, (_, i) => i / 200);
const normalise = (values) => {
  const total = values.reduce((a, b) => a + b, 0);
  return values.map((v) => v / total);
};
const baseline = normalise(grid.map((x) => bump(0.03, 0.005, x)));
const forged = normalise(grid.map((x) => bump(0.5, 0.01, x)));
const forgeryData = grid.map((x, i) => ({ mismatch_rate: x, baseline: baseline[i], observed: forged[i] }));

describe("Measurement Distribution Visualizer (testing.md 5.2)", () => {
  it("renders both threshold ReferenceLines as SVG elements", () => {
    const { container } = render(<Visualizer data={forgeryData} sA={0.075} sV={0.12} attackActive width={640} height={320} />);
    expect(container.querySelectorAll(".recharts-reference-line").length).toBeGreaterThanOrEqual(2);
    expect(container.querySelectorAll(".recharts-area").length).toBe(2);
  });

  it("shows the forged curve past s_v", () => {
    expect(massBeyond(forgeryData, 0.12, "observed")).toBeGreaterThan(0.99);
    expect(massBeyond(forgeryData, 0.12, "baseline")).toBeLessThan(0.01);
    render(<Visualizer data={forgeryData} sA={0.075} sV={0.12} attackActive width={640} height={320} />);
    expect(screen.getByTestId("mass-beyond-sv")).toHaveTextContent("100.0%");
  });

  it("shows a placeholder without data", () => {
    render(<Visualizer data={[]} sA={0.075} sV={0.12} />);
    expect(screen.getByText(/awaiting measurement distribution/i)).toBeInTheDocument();
  });
});
