import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BarChart3, Moon } from "lucide-react";
import "./styles.css";

function BaselineShell() {
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark"><BarChart3 size={18} /></span>
          <span>衡镜 BI</span>
          <small>M3 bundle baseline</small>
        </div>
        <button className="icon-button" type="button" aria-label="主题基线"><Moon size={17} /></button>
      </header>
      <main className="main-content">
        <div className="dashboard-heading"><div><h1>Dashboard shell baseline</h1></div></div>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BaselineShell />
  </StrictMode>,
);
