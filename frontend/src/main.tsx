
  import { createRoot } from "react-dom/client";
  import App from "./app/App.tsx";
  import "./styles/index.css";
  import { initPwaInstall } from "./lib/pwaInstall";

  initPwaInstall();

  createRoot(document.getElementById("root")!).render(<App />);
  