# Navbar browser regression gate

From the repository root:

```sh
python EduBac/manage.py test browser_tests --settings=browser_tests.settings --noinput
```

Run this check before publishing navbar/template/CSS changes. It exits nonzero
on failure and is also registered as the `navbar-browser` validation command.
This does not deploy the application.

Python dependencies, including Playwright, are in `EduBac/requirements.txt`.
Chromium is available in Replit; elsewhere install the matching browser with
`python -m playwright install chromium` (and its OS dependencies), or set
`CHROMIUM_EXECUTABLE` to an installed Chromium binary.
The suite needs access to the same Bootstrap, icon and jQuery CDNs as the app.
Missing browser/CDN dependencies fail rather than silently skip tests.

The Django static live server uses an isolated in-memory test database. No
development data, user credentials, auth bypasses, injected cookies, rendered
HTML fixtures, or production server are used. Test student and teacher accounts
submit the actual CSRF-protected login form in Chromium; a reload and protected
notification API request verify the resulting session.

Coverage: guest/student/teacher at 360, 375, 390, 414, 430, 768, 1024 and 1440px.
Each case checks header containment, control overlap, content offset and document
overflow, in light and dark themes. Keyboard Tab/Enter/Space, menu arrows and
Escape exercise page/account menus, notifications (including a real mark-all
request), theme persistence, signup/login navigation and logout. Menu destinations
are checked against Django URL names. Open menus must fit the viewport.
Animations remain enabled; tests wait for entry transitions rather than
disabling motion or changing application styles.

On failure, screenshots are saved under `test-results/navbar/` relative to the
working directory, named by role and viewport. Django subtest output identifies
the failing role/width and assertion. The public preview screenshot tool cannot
verify signed-in UI; these browser sessions do.

For focused diagnosis, set `NAVBAR_TEST_WIDTHS=390,414` before the same command
to run selected widths; leave it unset for the full publish gate.
