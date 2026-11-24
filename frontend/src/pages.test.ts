import { describe, expect, it } from "vitest";
import dashboard from "../index.html?raw";
import foi from "../foi.html?raw";

// OpenStreetMap blocks map tiles requested with no Referer ("Access blocked" on every tile), so neither page may
// turn the referrer off. Sending just the site's address ("origin") is enough for it.
describe("pages let the base map load", () => {
  it.each([["index.html", dashboard], ["foi.html", foi]])("%s doesn't send requests without a referrer", (_, html) => {
    expect(html).not.toMatch(/name="referrer"\s+content="no-referrer"/);
    expect(html).not.toMatch(/referrerpolicy="no-referrer"/i);
  });
});
