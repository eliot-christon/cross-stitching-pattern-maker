import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DmcThread, NearThread } from "./api";
import { clearThreadTable, ThreadPicker } from "./ThreadPicker";

const BLACK = { code: "310", name: "Black", rgb: [0, 0, 0] as [number, number, number] };

const NEAREST: NearThread[] = [
  { code: "3371", name: "Black Brown", rgb: [30, 17, 8], distance: 4.2 },
  { code: "939", name: "Navy Blue Very Dark", rgb: [27, 40, 83], distance: 9.1 },
  { code: "3799", name: "Pewter Grey Very Dark", rgb: [66, 66, 66], distance: 12.5 },
];

const WHITES: DmcThread[] = [
  { code: "746", name: "Off White", rgb: [252, 252, 238] },
  { code: "B5200", name: "Snow White", rgb: [255, 255, 255] },
  { code: "Blanc", name: "White", rgb: [252, 251, 248] },
  { code: "3865", name: "Winter White", rgb: [249, 247, 241] },
  { code: "01", name: "White Tin", rgb: [227, 227, 230] },
  { code: "310", name: "Black", rgb: [0, 0, 0] },
];

const TWENTY_TWOS: DmcThread[] = [
  { code: "225", name: "Shell Pink Ultra Very Light", rgb: [255, 223, 213] },
  { code: "224", name: "Shell Pink Very Light", rgb: [235, 183, 175] },
  { code: "223", name: "Shell Pink Light", rgb: [204, 132, 124] },
  { code: "3722", name: "Shell Pink Medium", rgb: [188, 108, 100] },
  { code: "22", name: "Alizarin", rgb: [190, 46, 42] },
];

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** fetch answering the table with `table` and any nearest call with `nearest`. */
function stubApi(table: DmcThread[], nearest: Response | (() => Response)) {
  const fetchMock = vi.fn((url: string) =>
    Promise.resolve(
      url === "/api/threads" ? json(200, table) : typeof nearest === "function" ? nearest() : nearest,
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function choiceCodes(sectionName: string): string[] {
  const section = screen.getByRole("region", { name: sectionName });
  return within(section)
    .queryAllByRole("button")
    .map((button) => button.querySelector(".thread-choice-code")?.textContent ?? "");
}

beforeEach(() => {
  clearThreadTable();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ThreadPicker", () => {
  it("is a dialog named for the thread, listing its nearest threads first, in order", async () => {
    stubApi(WHITES, () => json(200, NEAREST));
    render(<ThreadPicker from={BLACK} onPick={vi.fn()} onClose={vi.fn()} />);

    expect(screen.getByRole("dialog", { name: "Replace DMC 310 Black" })).toBeInTheDocument();
    await screen.findByText("Black Brown");
    expect(choiceCodes("Nearest threads")).toEqual(["3371", "939", "3799"]);
    const first = within(screen.getByRole("region", { name: "Nearest threads" })).getAllByRole(
      "button",
    )[0];
    expect(first).toHaveTextContent("Black Brown");
    const swatch = first?.querySelector<HTMLElement>(".swatch");
    expect(swatch?.style.backgroundColor).toBe("rgb(30, 17, 8)");
  });

  it("finds threads by name or code, case-insensitive, in table order", async () => {
    stubApi(WHITES, () => json(200, []));
    render(<ThreadPicker from={BLACK} onPick={vi.fn()} onClose={vi.fn()} />);
    const search = screen.getByRole("searchbox");

    fireEvent.change(search, { target: { value: "WHITE" } });
    await screen.findByText("Off White");
    expect(choiceCodes("All threads")).toEqual(["746", "B5200", "Blanc", "3865", "01"]);

    fireEvent.change(search, { target: { value: "blanc" } });
    expect(choiceCodes("All threads")).toEqual(["Blanc"]);
  });

  it("puts an exact code match first", async () => {
    stubApi(TWENTY_TWOS, () => json(200, []));
    render(
      <ThreadPicker
        from={{ code: "666", name: "Bright Red", rgb: [227, 29, 66] }}
        onPick={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "22" } });
    await screen.findByText("Alizarin");
    expect(choiceCodes("All threads")).toEqual(["22", "225", "224", "223", "3722"]);
  });

  it("never offers the thread being replaced", async () => {
    stubApi(WHITES, () => json(200, [{ ...BLACK, distance: 0 }, ...NEAREST]));
    render(<ThreadPicker from={BLACK} onPick={vi.fn()} onClose={vi.fn()} />);
    await screen.findByText("Black Brown");

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "310" } });

    expect(choiceCodes("Nearest threads")).not.toContain("310");
    expect(choiceCodes("All threads")).not.toContain("310");
  });

  it("hands the chosen code back once, and closes on Escape", async () => {
    stubApi(WHITES, () => json(200, NEAREST));
    const onPick = vi.fn();
    const onClose = vi.fn();
    render(<ThreadPicker from={BLACK} onPick={onPick} onClose={onClose} />);

    fireEvent.click(await screen.findByText("Black Brown"));
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick).toHaveBeenCalledWith("3371");

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("asks for the table once, however many pickers open", async () => {
    const fetchMock = stubApi(WHITES, () => json(200, NEAREST));
    const first = render(<ThreadPicker from={BLACK} onPick={vi.fn()} onClose={vi.fn()} />);
    await screen.findByText("Black Brown");
    first.unmount();

    render(<ThreadPicker from={WHITES[0] as DmcThread} onPick={vi.fn()} onClose={vi.fn()} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "snow" } });
    await screen.findByText("Snow White");

    const tableCalls = fetchMock.mock.calls.filter(([url]) => url === "/api/threads");
    expect(tableCalls).toHaveLength(1);
  });

  it("shows the nearest call's failure and still searches the table", async () => {
    stubApi(WHITES, () => json(404, { detail: "unknown DMC code: '310'" }));
    render(<ThreadPicker from={BLACK} onPick={vi.fn()} onClose={vi.fn()} />);

    expect(await screen.findByText("unknown DMC code: '310'")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "winter" } });
    expect(await screen.findByText("Winter White")).toBeInTheDocument();
  });
});
