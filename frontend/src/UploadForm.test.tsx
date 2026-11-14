import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Pattern } from "./pattern";
import { UploadForm } from "./UploadForm";

const PATTERN: Pattern = {
  width: 2,
  height: 1,
  fabric_count: 14,
  grid: [[0, 1]],
  key: [
    { code: "321", name: "Red", rgb: [199, 43, 59], stitches: 1, skeins: 1, symbol: "A" },
    { code: "310", name: "Black", rgb: [0, 0, 0], stitches: 1, skeins: 1, symbol: "B" },
  ],
  total_stitches: 2,
  finished_size: { width_in: 0.14, height_in: 0.07, width_cm: 0.36, height_cm: 0.18 },
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function chooseFile(): File {
  const file = new File(["png bytes"], "photo.png", { type: "image/png" });
  fireEvent.change(screen.getByLabelText("Image"), { target: { files: [file] } });
  return file;
}

function submitButton(): HTMLElement {
  return screen.getByRole("button", { name: /convert/i });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("UploadForm", () => {
  it("starts with the default settings and submit disabled until a file is chosen", () => {
    render(<UploadForm />);

    expect(screen.getByLabelText("Width (stitches)")).toHaveValue(100);
    expect(screen.getByLabelText("Max colours")).toHaveValue(20);
    expect(screen.getByLabelText("Fabric count")).toHaveValue(14);
    expect(submitButton()).toBeDisabled();

    chooseFile();

    expect(submitButton()).toBeEnabled();
  });

  it("posts the chosen file with the values entered", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(json(200, PATTERN)));
    vi.stubGlobal("fetch", fetchMock);
    render(<UploadForm />);

    const file = chooseFile();
    fireEvent.change(screen.getByLabelText("Width (stitches)"), { target: { value: "40" } });
    fireEvent.change(screen.getByLabelText("Max colours"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("Fabric count"), { target: { value: "16" } });
    fireEvent.click(submitButton());

    expect(await screen.findByRole("table", { name: "Thread key" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/patterns");
    const body = init.body as FormData;
    expect((body.get("image") as File).name).toBe(file.name);
    expect(body.get("width")).toBe("40");
    expect(body.get("max_colours")).toBe("4");
    expect(body.get("fabric_count")).toBe("16");
  });

  it("shows a busy state while the request is in flight, then the preview", async () => {
    let resolve: (response: Response) => void = () => undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((r) => {
            resolve = r;
          }),
      ),
    );
    render(<UploadForm />);

    chooseFile();
    fireEvent.click(submitButton());

    expect(screen.getByRole("status")).toHaveTextContent(/converting/i);
    expect(submitButton()).toBeDisabled();

    await act(async () => {
      resolve(json(200, PATTERN));
    });

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(submitButton()).toBeEnabled();
    expect(screen.getByText("321")).toBeInTheDocument();
    expect(screen.getByText("310")).toBeInTheDocument();
  });

  it("shows the API's message on an error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(json(400, { detail: "the upload is not a decodable image" }))),
    );
    render(<UploadForm />);

    chooseFile();
    fireEvent.click(submitButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "the upload is not a decodable image",
    );
  });

  it("clears the error when the next submit succeeds", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(400, { detail: "the upload is not a decodable image" }))
      .mockResolvedValueOnce(json(200, PATTERN));
    vi.stubGlobal("fetch", fetchMock);
    render(<UploadForm />);

    chooseFile();
    fireEvent.click(submitButton());
    expect(await screen.findByRole("alert")).toBeInTheDocument();

    fireEvent.click(submitButton());

    expect(await screen.findByRole("table", { name: "Thread key" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("clears the previous preview when the next submit fails", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(200, PATTERN))
      .mockResolvedValueOnce(json(400, { detail: "the upload is not a decodable image" }));
    vi.stubGlobal("fetch", fetchMock);
    render(<UploadForm />);

    chooseFile();
    fireEvent.click(submitButton());
    expect(await screen.findByRole("table", { name: "Thread key" })).toBeInTheDocument();

    fireEvent.click(submitButton());

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Thread key" })).not.toBeInTheDocument();
  });

  it("posts a width of 0 as typed: the form does no range check", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        json(422, {
          detail: [{ loc: ["body", "width"], msg: "Input should be greater than or equal to 1" }],
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<UploadForm />);

    chooseFile();
    fireEvent.change(screen.getByLabelText("Width (stitches)"), { target: { value: "0" } });
    fireEvent.click(submitButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "width: Input should be greater than or equal to 1",
    );
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.body as FormData).get("width")).toBe("0");
  });

  it("shows a message, not a crash, when the server cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));
    render(<UploadForm />);

    chooseFile();
    fireEvent.click(submitButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(/cannot reach the server/i);
    expect(submitButton()).toBeEnabled();
  });
});
