// Shared battlefield card sizing. Player cards (9:16) and enemy creatures (1:1)
// are laid out to the SAME width so the two sides read as equals; the width scales
// with the window. Player cards are therefore taller (portrait), creatures square.
export const CARD_WIDTH = "clamp(140px, 15vh, 220px)";
export const BOSS_CARD_WIDTH = "clamp(210px, 22.5vh, 330px)"; // ~1.5× (dormant)
export const TOKEN_CARD_WIDTH = "clamp(70px, 7.5vh, 110px)";
