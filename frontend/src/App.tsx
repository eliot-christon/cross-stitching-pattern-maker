import { StitchedHeart, StitchRule } from "./motif";
import { UploadForm } from "./UploadForm";

export function App() {
  return (
    <div className="app">
      <header className="app-header">
        <StitchedHeart size={36} />
        <div>
          <h1>Cross-stitch pattern maker</h1>
          <p className="tagline">From a picture to a chart of DMC threads.</p>
        </div>
      </header>
      <StitchRule />
      <main>
        <UploadForm />
      </main>
    </div>
  );
}
