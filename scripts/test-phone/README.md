# Test phone (mock passport only)

Stands in for the ZKPassport app so the passport page can be tested in a real browser without
a real passport. It only answers requests made in dev mode, and only proves from a mock
passport of the fictional "Zero Knowledge Republic".

1. Open `/passport` on the site, press **Start**, open "Test mode: the request link" and copy it.
2. Run (PowerShell, from the repo folder):

   ```
   $env:REQUEST_URL = "<paste the link>"
   docker run --rm -e REQUEST_URL -v "${PWD}\scripts\test-phone:/phone:ro" oven/bun:1.4.5@sha256:3aa040e5445efa09d75bb428a64ba50db13e2b3ac9b6b0c7f145615f62b2ee18 bash /phone/test-phone.sh
   ```

   Add `-e DATE_OF_BIRTH=2015-01-01` to try a minor: no proof can be made.
3. The browser shows "Checking the proof..." and then the members page.

The first run downloads and builds ZKPassport's packages, so it takes a few minutes.
