/*
 * Native CFBundleExecutable for MessageManager.app.
 *
 * Full Disk Access is granted to this Mach-O binary (the app). A shell-script
 * executable cannot reliably pass that permission to a child Python process, so
 * this launcher copies ~/Library/Messages/chat.db* into Application Support and
 * then starts the Python server via launch.sh.
 */
#include <copyfile.h>
#include <errno.h>
#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static void join2(char *out, size_t n, const char *a, const char *b) {
  snprintf(out, n, "%s/%s", a, b);
}

static int ensure_dir(const char *path) {
  char tmp[PATH_MAX];
  snprintf(tmp, sizeof(tmp), "%s", path);
  size_t len = strlen(tmp);
  if (len == 0) return -1;
  for (char *p = tmp + 1; *p; p++) {
    if (*p == '/') {
      *p = '\0';
      mkdir(tmp, 0755);
      *p = '/';
    }
  }
  return mkdir(tmp, 0755);
}

static void copy_if_exists(const char *src, const char *dst) {
  struct stat st;
  if (stat(src, &st) != 0) return;
  if (copyfile(src, dst, NULL, COPYFILE_ALL) != 0) {
    fprintf(stderr, "MessageManager: copy failed %s -> %s (%s)\n", src, dst, strerror(errno));
  }
}

static void refresh_messages_cache(const char *home, const char *cache_dir) {
  char src[PATH_MAX], dst[PATH_MAX];
  ensure_dir(cache_dir);

  join2(src, sizeof(src), home, "Library/Messages/chat.db");
  join2(dst, sizeof(dst), cache_dir, "chat.db");
  copy_if_exists(src, dst);

  join2(src, sizeof(src), home, "Library/Messages/chat.db-wal");
  join2(dst, sizeof(dst), cache_dir, "chat.db-wal");
  copy_if_exists(src, dst);

  join2(src, sizeof(src), home, "Library/Messages/chat.db-shm");
  join2(dst, sizeof(dst), cache_dir, "chat.db-shm");
  copy_if_exists(src, dst);
}

int main(int argc, char **argv) {
  (void)argc;
  (void)argv;

  char exe[PATH_MAX];
  uint32_t size = sizeof(exe);
  if (_NSGetExecutablePath(exe, &size) != 0) {
    fprintf(stderr, "MessageManager: cannot resolve executable path\n");
    return 1;
  }
  char resolved[PATH_MAX];
  if (!realpath(exe, resolved)) {
    strncpy(resolved, exe, sizeof(resolved) - 1);
    resolved[sizeof(resolved) - 1] = '\0';
  }

  char macos_dir[PATH_MAX];
  strncpy(macos_dir, resolved, sizeof(macos_dir) - 1);
  macos_dir[sizeof(macos_dir) - 1] = '\0';
  char *slash = strrchr(macos_dir, '/');
  if (!slash) return 1;
  *slash = '\0';

  char script[PATH_MAX];
  snprintf(script, sizeof(script), "%s/../Resources/app/scripts/macos/launch.sh", macos_dir);
  char script_real[PATH_MAX];
  if (!realpath(script, script_real)) {
    fprintf(stderr, "MessageManager: launch.sh missing at %s\n", script);
    return 1;
  }

  const char *home = getenv("HOME");
  if (!home || !home[0]) home = "/Users/Shared";

  char cache_dir[PATH_MAX];
  snprintf(
      cache_dir,
      sizeof(cache_dir),
      "%s/Library/Application Support/MessageManager/messages-cache",
      home);
  refresh_messages_cache(home, cache_dir);

  setenv("THREAD_LEDGER_MESSAGES_CACHE", cache_dir, 1);

  execl("/bin/bash", "bash", script_real, (char *)NULL);
  fprintf(stderr, "MessageManager: failed to exec launch.sh (%s)\n", strerror(errno));
  return 1;
}
