import React, { useEffect, useRef, useState } from "../react-shim.js";
import { Icon } from "./icons.jsx";
import { api } from "../lib/apiClient.js";
import { useDebouncedValue } from "../lib/hooks.js";
import { hasPermission, PERMISSIONS } from "../lib/session.js";

/**
 * Global command-style search across listings and users. Debounced,
 * abort-safe, keyboard navigable, permission-aware (only queries resources
 * the signed-in staff member can read).
 */
export function GlobalSearch({ staff, onOpenListing, onOpenUsers }) {
  const [term, setTerm] = useState("");
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState({ listings: [], users: [] });
  const [activeIndex, setActiveIndex] = useState(-1);
  const debounced = useDebouncedValue(term, 250);
  const containerRef = useRef(null);

  const canListings = hasPermission(staff, PERMISSIONS.LISTINGS_READ);
  const canUsers = hasPermission(staff, PERMISSIONS.USERS_MANAGE);

  useEffect(() => {
    if (!debounced || debounced.trim().length < 2) {
      setResults({ listings: [], users: [] });
      return undefined;
    }
    const controller = new AbortController();
    (async () => {
      const [listings, users] = await Promise.all([
        canListings
          ? api.get("/listings", { search: debounced, limit: 5 }, controller.signal).catch(() => ({ listings: [] }))
          : Promise.resolve({ listings: [] }),
        canUsers
          ? api.get("/users", { search: debounced, limit: 5 }, controller.signal).catch(() => ({ users: [] }))
          : Promise.resolve({ users: [] }),
      ]);
      setResults({ listings: listings.listings || [], users: users.users || [] });
      setActiveIndex(-1);
    })();
    return () => controller.abort();
  }, [debounced, canListings, canUsers]);

  useEffect(() => {
    function handleClickOutside(event) {
      if (containerRef.current && !containerRef.current.contains(event.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const flatResults = [
    ...results.listings.map((item) => ({ type: "listing", item })),
    ...results.users.map((item) => ({ type: "user", item })),
  ];

  function selectResult(entry) {
    setOpen(false);
    setTerm("");
    if (entry.type === "listing") onOpenListing(entry.item.id);
    else onOpenUsers(entry.item);
  }

  function handleKeyDown(event) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, flatResults.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (event.key === "Enter") {
      if (activeIndex >= 0 && flatResults[activeIndex]) {
        event.preventDefault();
        selectResult(flatResults[activeIndex]);
      }
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className="global-search" ref={containerRef}>
      <label htmlFor="global-search-input" className="sr-only">
        Глобальний пошук оголошень і користувачів
      </label>
      <Icon name="search" size={16} className="global-search-icon" />
      <input
        id="global-search-input"
        type="search"
        className="global-search-input"
        placeholder="Пошук оголошень, користувачів…"
        role="combobox"
        aria-expanded={open}
        aria-controls="global-search-results"
        aria-autocomplete="list"
        value={term}
        onFocus={() => setOpen(true)}
        onChange={(event) => {
          setTerm(event.target.value);
          setOpen(true);
        }}
        onKeyDown={handleKeyDown}
        data-testid="global-search-input"
      />
      {open && term.trim().length >= 2 ? (
        <ul
          id="global-search-results"
          className="global-search-results"
          role="listbox"
          data-testid="global-search-results"
        >
          {flatResults.length === 0 ? (
            <li className="global-search-empty" role="presentation">
              Нічого не знайдено
            </li>
          ) : (
            flatResults.map((entry, index) => (
              <li key={`${entry.type}-${entry.item.id}`} role="option" aria-selected={index === activeIndex}>
                <button
                  type="button"
                  className={`global-search-result${index === activeIndex ? " active" : ""}`}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => selectResult(entry)}
                  data-testid={`global-search-result-${entry.type}-${entry.item.id}`}
                >
                  <Icon name={entry.type === "listing" ? "home" : "users"} size={15} />
                  <span className="global-search-result-title">
                    {entry.type === "listing" ? entry.item.title : entry.item.name || entry.item.email}
                  </span>
                  <span className="global-search-result-meta">
                    {entry.type === "listing" ? `${entry.item.city}, ${entry.item.district}` : entry.item.email}
                  </span>
                </button>
              </li>
            ))
          )}
        </ul>
      ) : null}
    </div>
  );
}
