
  import { createRoot } from "react-dom/client";
  import App from "./app/App.tsx";
  import { MobileBlockedScreen } from "./app/components/MobileBlockedScreen";
  import "./styles/index.css";
  import { initPwaInstall, isMobileDevice } from "./lib/pwaInstall";

  initPwaInstall();

  // Desktop-only: phones and tablets get the notice instead of the app, so
  // the login, dashboard and API calls never load there.
  createRoot(document.getElementById("root")!).render(
    isMobileDevice() ? <MobileBlockedScreen /> : <App />
  );
