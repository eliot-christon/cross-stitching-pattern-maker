import { StitchedTitle, StitchRule } from "./motif";
import { UploadForm } from "./UploadForm";

const TITLE = "Cross-stitch pattern maker";

export function App() {
  return (
    <div className="app">
      <header className="app-header">
        <h1>
          <span className="visually-hidden">{TITLE}</span>
          <StitchedTitle lines={["CROSS-STITCH", "PATTERN MAKER"]} />
        </h1>
        <p className="tagline">From a picture to a chart of DMC threads.</p>
      </header>
      <StitchRule />
      <main>
        <UploadForm />
      </main>
    </div>
  );
}
