import React, { useState } from "../../react-shim.js";
import { PageHeader, Tabs, TabPanel } from "../../components/Layout.jsx";
import { hasPermission, PERMISSIONS } from "../../lib/session.js";
import { getPref, setPref } from "../../lib/prefs.js";
import { ModerationListings } from "./ModerationListings.jsx";
import { Verifications } from "./Verifications.jsx";
import { ListingReports } from "./ListingReports.jsx";

export function Moderation({ staff }) {
  const tabs = [
    hasPermission(staff, PERMISSIONS.LISTINGS_MODERATE) ? { id: "listings", label: "Оголошення" } : null,
    hasPermission(staff, PERMISSIONS.VERIFICATIONS_MANAGE) ? { id: "verifications", label: "Верифікації" } : null,
    hasPermission(staff, PERMISSIONS.REPORTS_MANAGE) ? { id: "reports", label: "Скарги" } : null,
  ].filter(Boolean);
  const [activeTab, setActiveTabState] = useState(() => {
    const saved = getPref("moderation.activeTab", tabs[0]?.id);
    return tabs.some((tab) => tab.id === saved) ? saved : tabs[0]?.id;
  });
  function setActiveTab(nextTab) {
    setActiveTabState(nextTab);
    setPref("moderation.activeTab", nextTab);
  }

  return (
    <div className="page">
      <PageHeader title="Модерація" description="Черга оголошень, верифікації та скарги користувачів." />
      <Tabs idBase="moderation" tabs={tabs} activeId={activeTab} onChange={setActiveTab} />
      <TabPanel id="listings" idBase="moderation" active={activeTab === "listings"}>
        <ModerationListings staff={staff} />
      </TabPanel>
      <TabPanel id="verifications" idBase="moderation" active={activeTab === "verifications"}>
        <Verifications />
      </TabPanel>
      <TabPanel id="reports" idBase="moderation" active={activeTab === "reports"}>
        <ListingReports staff={staff} />
      </TabPanel>
    </div>
  );
}
