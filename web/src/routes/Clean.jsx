import { useSearchParams } from "react-router-dom";
import { CaptionLane } from "../components/CaptionLane.jsx";
import { useSurfaceClass } from "../lib/stages.js";
import { useCaptions } from "../lib/useCaptions.js";

export default function Clean() {
  useSurfaceClass("clean");
  const [params] = useSearchParams();
  const stageId = params.get("stage") || "1";
  const lang = params.get("lang") === "en" ? "en" : "es";
  const mock = params.get("mock") === "1";
  const { segments } = useCaptions({ stageId, lang, mock });
  const tail = segments.slice(-4);

  return (
    <main className="clean-root">
      <div className="clean-stack">
        <CaptionLane segments={tail} />
      </div>
    </main>
  );
}
