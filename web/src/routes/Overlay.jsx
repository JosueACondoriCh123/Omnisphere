/*
  OBS Browser Source:
  http://localhost:8088/overlay/1?theme=obs&lang=es&size=md
*/
import { useParams, useSearchParams } from "react-router-dom";
import { CaptionLane } from "../components/CaptionLane.jsx";
import { useSurfaceClass } from "../lib/stages.js";
import { useCaptions } from "../lib/useCaptions.js";

export default function Overlay() {
  useSurfaceClass("overlay");
  const { stageId = "1" } = useParams();
  const [params] = useSearchParams();
  const requestedTheme = params.get("theme");
  const theme = ["obs", "light", "dark"].includes(requestedTheme)
    ? requestedTheme
    : "obs";
  const lang = params.get("lang") === "en" ? "en" : "es";
  const requestedSize = params.get("size");
  const size = ["sm", "md", "lg"].includes(requestedSize)
    ? requestedSize
    : "md";
  const mock = params.get("mock") === "1";
  const { segments } = useCaptions({ stageId, lang, mock });
  const tail = segments.slice(-3);

  return (
    <main
      className={`overlay-root theme-${theme} size-${size}`}
      data-transparent="true"
    >
      <div className="lower-third" data-safe="1">
        <CaptionLane segments={tail} />
      </div>
    </main>
  );
}
