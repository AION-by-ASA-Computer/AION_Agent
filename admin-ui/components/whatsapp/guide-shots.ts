/**
 * Highlight boxes for the screenshots of the WhatsApp setup guide
 * (`public/whatsapp-guide/<name>.png`), used by `WhatsAppGuideDialog`.
 *
 * Each box is expressed in % of the (already cropped) image so it keeps
 * its position at any rendered width. The images are privacy-redacted
 * (emails, phone numbers, IDs and tokens are masked irreversibly), so the
 * boxes only point at the UI element the user has to act on.
 *
 * Keep the keys in sync with the PNG file names and with the
 * `admin_whatsapp.guide.cap_<name with "_">` captions in every locale.
 */
import type { Mark } from "@/components/sso/MicrosoftSsoGuide";

export const WHATSAPP_SHOT_MARKS: Record<string, Mark[]> = {
  "app-details": [
    { x: 2.7, y: 38.7, w: 94.6, h: 9.3 },
    { x: 2.7, y: 67.6, w: 94.6, h: 9.3 },
    { x: 90.1, y: 81.5, w: 7.2, h: 9.5 },
  ],
  "app-use-case": [
    { x: 2.8, y: 64.4, w: 23.9, h: 5.8 },
    { x: 29.9, y: 68.1, w: 67.6, h: 17.2 },
    { x: 90.3, y: 88.3, w: 7.2, h: 6.6 },
  ],
  "app-business-portfolio": [
    { x: 2.6, y: 61.9, w: 14.0, h: 8.0 },
    { x: 90.5, y: 84.6, w: 7.2, h: 8.7 },
  ],
  "app-review-create": [
    { x: 89.1, y: 93.5, w: 8.7, h: 4.7 },
  ],
  "use-cases-customize": [
    { x: 85.0, y: 57.7, w: 12.5, h: 18.5 },
  ],
  "add-phone-number": [
    { x: 1.6, y: 61.5, w: 23.1, h: 6.4 },
    { x: 31.4, y: 89.6, w: 17.3, h: 7.1 },
  ],
  "whatsapp-profile": [
    { x: 27.1, y: 32.0, w: 70.6, h: 5.6 },
    { x: 27.1, y: 67.5, w: 70.6, h: 5.5 },
    { x: 86.7, y: 91.6, w: 11.0, h: 5.6 },
  ],
  "phone-verify": [
    { x: 27.0, y: 61.0, w: 7.9, h: 9.7 },
    { x: 86.7, y: 78.5, w: 11.1, h: 14.4 },
  ],
  "messaging-account": [
    { x: 27.0, y: 30.6, w: 70.7, h: 11.2 },
    { x: 86.0, y: 83.0, w: 12.0, h: 12.1 },
  ],
  "registered-ids": [
    { x: 32.5, y: 73.0, w: 20.9, h: 4.0 },
    { x: 36.2, y: 88.3, w: 21.9, h: 4.3 },
  ],
  "system-users": [
    { x: 2.5, y: 84.7, w: 16.6, h: 13.8 },
    { x: 90.2, y: 10.0, w: 8.1, h: 15.9 },
  ],
  "system-user-create": [
    { x: 4.8, y: 36.5, w: 90.3, h: 10.6 },
    { x: 4.8, y: 66.3, w: 90.3, h: 10.8 },
    { x: 60.5, y: 82.7, w: 34.7, h: 10.8 },
  ],
  "system-user-assign": [
    { x: 57.4, y: 91.4, w: 14.3, h: 5.7 },
  ],
  "assign-assets-dialog": [
    { x: 1.0, y: 18.5, w: 21.1, h: 5.1 },
    { x: 23.0, y: 30.1, w: 29.9, h: 6.9 },
    { x: 54.8, y: 59.4, w: 4.2, h: 4.0 },
    { x: 82.9, y: 90.1, w: 14.8, h: 6.3 },
  ],
  "assets-assigned": [
    { x: 64.6, y: 24.3, w: 11.2, h: 8.3 },
    { x: 31.9, y: 88.8, w: 64.7, h: 8.3 },
  ],
  "token-app": [
    { x: 27.4, y: 13.5, w: 69.8, h: 5.7 },
    { x: 85.7, y: 90.6, w: 11.5, h: 5.8 },
  ],
  "token-expiry": [
    { x: 27.4, y: 22.5, w: 20.6, h: 3.9 },
    { x: 86.1, y: 90.5, w: 11.5, h: 5.8 },
  ],
  "token-permissions": [
    { x: 27.8, y: 57.4, w: 69.0, h: 5.3 },
    { x: 27.8, y: 63.0, w: 69.0, h: 5.4 },
    { x: 82.8, y: 90.7, w: 14.5, h: 5.8 },
  ],
  "token-created": [
    { x: 27.3, y: 18.1, w: 70.1, h: 5.7 },
  ],
  "temp-token": [
    { x: 2.3, y: 58.8, w: 76.5, h: 15.8 },
  ],
  "app-secret": [
    { x: 0.4, y: 84.0, w: 21.3, h: 5.4 },
    { x: 64.2, y: 10.6, w: 34.1, h: 6.1 },
  ],
  "app-unpublished": [
    { x: 0.4, y: 66.2, w: 21.0, h: 6.8 },
  ],
};
