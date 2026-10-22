import { Monitor } from "lucide-react";
import agrisureLogo from "@/assets/agrisuregis-logo.png";

// Shown instead of the whole app on phones and tablets (2026-10-13, per
// Cristian): AgriSureGIS is desktop-only. Same gradient and branding as
// LoginScreen. Detection lives in isMobileDevice() (lib/pwaInstall.ts).
export function MobileBlockedScreen() {
  return (
    <div
      className="h-screen overflow-y-auto flex items-center justify-center px-6 py-8"
      style={{
        background: "linear-gradient(145deg, #0f4023 0%, #166534 40%, #1e3a5f 100%)",
      }}
    >
      <div className="w-full max-w-sm text-center">
        <img src={agrisureLogo} alt="AgriSureGIS logo" className="h-16 w-auto mx-auto mb-2" />
        <h1 className="text-white text-2xl font-black tracking-tight">AgriSureGIS</h1>
        <p className="text-white/90 text-base mt-1">Automated Disaster Risk Assessment System</p>

        <div className="bg-white rounded-2xl shadow-2xl mt-6 px-6 py-6 flex flex-col items-center">
          <div className="w-14 h-14 rounded-full bg-[#166534]/10 flex items-center justify-center mb-4">
            <Monitor size={28} className="text-[#166534]" />
          </div>
          <p className="text-lg font-black text-gray-800">Desktop Only</p>
          <p className="text-sm text-gray-600 mt-2">
            AgriSureGIS is available on desktop only. Please open it on a computer using Chrome or Edge.
          </p>
        </div>

        <p className="text-white/70 text-xs mt-4">
          Authorized Personnel Only · For technical support contact the ICT Division
        </p>
      </div>
    </div>
  );
}
