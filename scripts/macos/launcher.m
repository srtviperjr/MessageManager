/*
 * Native AppKit CFBundleExecutable for MessageManager.app.
 *
 * Stays an NSApplication for the Dock (stops the bounce), copies Messages +
 * Contacts under Full Disk Access, then runs launch.sh as a child task.
 *
 * Also supports: MessageManager --refresh-cache
 * (headless re-copy with progress JSON for the web UI).
 */
#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>
#include <copyfile.h>
#include <dirent.h>
#include <errno.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static void join2(char *out, size_t n, const char *a, const char *b) {
  snprintf(out, n, "%s/%s", a, b);
}

static int ensure_dir(const char *path) {
  char tmp[PATH_MAX];
  snprintf(tmp, sizeof(tmp), "%s", path);
  for (char *p = tmp + 1; *p; p++) {
    if (*p == '/') {
      *p = '\0';
      mkdir(tmp, 0755);
      *p = '/';
    }
  }
  return mkdir(tmp, 0755);
}

typedef struct {
  const char *label;
  off_t total;
  int percent_start;
  int percent_end;
  char status_path[PATH_MAX];
} CopyProgressCtx;

static void write_progress_json(const char *path, const char *message, int percent,
                                int done, const char *error) {
  FILE *f = fopen(path, "w");
  if (!f) return;
  fputc('{', f);
  fprintf(f, "\"percent\":%d,", percent);
  fprintf(f, "\"done\":%s,", done ? "true" : "false");
  fprintf(f, "\"message\":\"");
  if (message) {
    for (const char *p = message; *p; p++) {
      if (*p == '"' || *p == '\\') fputc('\\', f);
      if (*p == '\n' || *p == '\r') continue;
      fputc(*p, f);
    }
  }
  fputc('"', f);
  if (error && error[0]) {
    fprintf(f, ",\"error\":\"");
    for (const char *p = error; *p; p++) {
      if (*p == '"' || *p == '\\') fputc('\\', f);
      if (*p == '\n' || *p == '\r') continue;
      fputc(*p, f);
    }
    fputc('"', f);
  }
  if (done && !(error && error[0])) {
    fprintf(f, ",\"ok\":true,\"method\":\"native\"");
  }
  fputc('}', f);
  fputc('\n', f);
  fclose(f);
}

static int copy_progress_cb(int what, int stage, copyfile_state_t state,
                            const char *src, const char *dst, void *ctx) {
  (void)what;
  (void)stage;
  (void)src;
  (void)dst;
  CopyProgressCtx *c = (CopyProgressCtx *)ctx;
  if (!c || !state) return COPYFILE_CONTINUE;
  off_t copied = 0;
  copyfile_state_get(state, COPYFILE_STATE_COPIED, &copied);
  int pct = c->percent_start;
  if (c->total > 0) {
    double frac = (double)copied / (double)c->total;
    if (frac > 1.0) frac = 1.0;
    pct = c->percent_start +
          (int)((c->percent_end - c->percent_start) * frac);
  }
  char msg[256];
  double mb = copied / (1024.0 * 1024.0);
  double total_mb = c->total / (1024.0 * 1024.0);
  snprintf(msg, sizeof(msg), "Copying %s: %.1f / %.1f MB", c->label, mb, total_mb);
  write_progress_json(c->status_path, msg, pct, 0, NULL);
  return COPYFILE_CONTINUE;
}

static void copy_if_exists(const char *src, const char *dst) {
  struct stat st;
  if (stat(src, &st) != 0) return;
  if (copyfile(src, dst, NULL, COPYFILE_ALL) != 0) {
    fprintf(stderr, "MessageManager: copy failed %s -> %s\n", src, dst);
  }
}

static int copy_if_exists_progress(const char *src, const char *dst,
                                   CopyProgressCtx *ctx) {
  struct stat st;
  if (stat(src, &st) != 0) return 0;
  ctx->total = st.st_size;
  copyfile_state_t state = copyfile_state_alloc();
  if (!state) {
    if (copyfile(src, dst, NULL, COPYFILE_ALL) != 0) return -1;
    return 0;
  }
  copyfile_state_set(state, COPYFILE_STATE_STATUS_CB, &copy_progress_cb);
  copyfile_state_set(state, COPYFILE_STATE_STATUS_CTX, ctx);
  int rc = copyfile(src, dst, state, COPYFILE_ALL);
  copyfile_state_free(state);
  return rc == 0 ? 0 : -1;
}

static void copy_db_trio(const char *src_db, const char *dst_db) {
  char src[PATH_MAX], dst[PATH_MAX];
  copy_if_exists(src_db, dst_db);
  snprintf(src, sizeof(src), "%s-wal", src_db);
  snprintf(dst, sizeof(dst), "%s-wal", dst_db);
  copy_if_exists(src, dst);
  snprintf(src, sizeof(src), "%s-shm", src_db);
  snprintf(dst, sizeof(dst), "%s-shm", dst_db);
  copy_if_exists(src, dst);
}

static void refresh_messages_cache(const char *home, const char *cache_dir) {
  char src[PATH_MAX], dst[PATH_MAX];
  ensure_dir(cache_dir);
  join2(src, sizeof(src), home, "Library/Messages/chat.db");
  join2(dst, sizeof(dst), cache_dir, "chat.db");
  copy_db_trio(src, dst);
}

static int refresh_messages_cache_progress(const char *home, const char *cache_dir,
                                           const char *status_path) {
  char src[PATH_MAX], dst[PATH_MAX];
  ensure_dir(cache_dir);
  join2(src, sizeof(src), home, "Library/Messages/chat.db");
  join2(dst, sizeof(dst), cache_dir, "chat.db");
  struct stat st;
  if (stat(src, &st) != 0) {
    write_progress_json(status_path, "Messages database not found", 0, 1,
                        "Open the Messages app once, then retry.");
    return 1;
  }
  CopyProgressCtx ctx;
  memset(&ctx, 0, sizeof(ctx));
  strncpy(ctx.status_path, status_path, sizeof(ctx.status_path) - 1);
  ctx.label = "Messages chat.db";
  ctx.percent_start = 5;
  ctx.percent_end = 75;
  write_progress_json(status_path, "Copying Messages chat.db…", 5, 0, NULL);
  if (copy_if_exists_progress(src, dst, &ctx) != 0) {
    char err[128];
    snprintf(err, sizeof(err), "copy failed (%s)", strerror(errno));
    write_progress_json(status_path, "Messages copy failed", 0, 1, err);
    return 2;
  }
  // WAL / SHM are usually small; copy without detailed progress.
  char src_wal[PATH_MAX], dst_wal[PATH_MAX], src_shm[PATH_MAX], dst_shm[PATH_MAX];
  snprintf(src_wal, sizeof(src_wal), "%s-wal", src);
  snprintf(dst_wal, sizeof(dst_wal), "%s-wal", dst);
  snprintf(src_shm, sizeof(src_shm), "%s-shm", src);
  snprintf(dst_shm, sizeof(dst_shm), "%s-shm", dst);
  copy_if_exists(src_wal, dst_wal);
  copy_if_exists(src_shm, dst_shm);
  write_progress_json(status_path, "Messages cache ready", 75, 0, NULL);
  return 0;
}

static void refresh_contacts_cache(const char *home, const char *cache_dir) {
  char src_root[PATH_MAX], sources_src[PATH_MAX], sources_dst[PATH_MAX];
  char db_src[PATH_MAX], db_dst[PATH_MAX];

  ensure_dir(cache_dir);
  join2(src_root, sizeof(src_root), home, "Library/Application Support/AddressBook");
  join2(db_src, sizeof(db_src), src_root, "AddressBook-v22.abcddb");
  join2(db_dst, sizeof(db_dst), cache_dir, "AddressBook-v22.abcddb");
  copy_db_trio(db_src, db_dst);

  join2(sources_src, sizeof(sources_src), src_root, "Sources");
  join2(sources_dst, sizeof(sources_dst), cache_dir, "Sources");
  ensure_dir(sources_dst);

  DIR *dir = opendir(sources_src);
  if (!dir) return;
  struct dirent *ent;
  while ((ent = readdir(dir)) != NULL) {
    if (ent->d_name[0] == '.') continue;
    char child_src[PATH_MAX], child_dst[PATH_MAX];
    join2(child_src, sizeof(child_src), sources_src, ent->d_name);
    join2(child_dst, sizeof(child_dst), sources_dst, ent->d_name);
    struct stat st;
    if (stat(child_src, &st) != 0 || !S_ISDIR(st.st_mode)) continue;
    ensure_dir(child_dst);
    join2(db_src, sizeof(db_src), child_src, "AddressBook-v22.abcddb");
    join2(db_dst, sizeof(db_dst), child_dst, "AddressBook-v22.abcddb");
    copy_db_trio(db_src, db_dst);
  }
  closedir(dir);
}

static BOOL resolve_paths(char *script_out, size_t script_n,
                          char *messages_cache, size_t messages_n,
                          char *contacts_cache, size_t contacts_n) {
  char exe[PATH_MAX];
  uint32_t size = sizeof(exe);
  if (_NSGetExecutablePath(exe, &size) != 0) return NO;
  char resolved[PATH_MAX];
  if (!realpath(exe, resolved)) {
    strncpy(resolved, exe, sizeof(resolved) - 1);
    resolved[sizeof(resolved) - 1] = '\0';
  }

  char macos_dir[PATH_MAX];
  strncpy(macos_dir, resolved, sizeof(macos_dir) - 1);
  macos_dir[sizeof(macos_dir) - 1] = '\0';
  char *slash = strrchr(macos_dir, '/');
  if (!slash) return NO;
  *slash = '\0';

  char script[PATH_MAX];
  snprintf(script, sizeof(script), "%s/../Resources/app/scripts/macos/launch.sh", macos_dir);
  if (!realpath(script, script_out)) return NO;

  const char *home = getenv("HOME");
  if (!home || !home[0]) home = "/Users/Shared";
  snprintf(messages_cache, messages_n,
           "%s/Library/Application Support/MessageManager/messages-cache", home);
  snprintf(contacts_cache, contacts_n,
           "%s/Library/Application Support/MessageManager/contacts-cache", home);

  refresh_messages_cache(home, messages_cache);
  refresh_contacts_cache(home, contacts_cache);
  setenv("THREAD_LEDGER_MESSAGES_CACHE", messages_cache, 1);
  setenv("THREAD_LEDGER_CONTACTS_CACHE", contacts_cache, 1);
  setenv("THREAD_LEDGER_MANAGED", "1", 1);
  return YES;
}

@interface MMAppDelegate : NSObject <NSApplicationDelegate>
@property(nonatomic, strong) NSTask *launchTask;
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) NSTimer *pollTimer;
@property(nonatomic, copy) NSString *baseURL;
@end

@implementation MMAppDelegate

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
  (void)notification;
  self.baseURL = @"http://127.0.0.1:8741";
  [self buildWindow];
  [self startLaunchScript];
  self.pollTimer = [NSTimer scheduledTimerWithTimeInterval:2.0
                                                    target:self
                                                  selector:@selector(pollServer)
                                                  userInfo:nil
                                                   repeats:YES];
}

- (void)buildWindow {
  NSRect frame = NSMakeRect(0, 0, 420, 168);
  self.window = [[NSWindow alloc] initWithContentRect:frame
                                            styleMask:(NSWindowStyleMaskTitled |
                                                       NSWindowStyleMaskClosable |
                                                       NSWindowStyleMaskMiniaturizable)
                                              backing:NSBackingStoreBuffered
                                                defer:NO];
  self.window.title = @"MessageManager";
  self.window.releasedWhenClosed = NO;
  [self.window center];

  NSView *content = self.window.contentView;
  NSTextField *title = [NSTextField labelWithString:@"MessageManager is running"];
  title.font = [NSFont boldSystemFontOfSize:15];
  title.translatesAutoresizingMaskIntoConstraints = NO;

  NSTextField *body = [NSTextField wrappingLabelWithString:
      @"The app is open in your browser. Keep this window open while you work.\n"
       @"Click Quit to stop the local server."];
  body.translatesAutoresizingMaskIntoConstraints = NO;

  NSButton *quit = [NSButton buttonWithTitle:@"Quit MessageManager"
                                      target:self
                                      action:@selector(quitApp:)];
  quit.bezelStyle = NSBezelStyleRounded;
  quit.keyEquivalent = @"q";
  quit.keyEquivalentModifierMask = NSEventModifierFlagCommand;
  quit.translatesAutoresizingMaskIntoConstraints = NO;

  [content addSubview:title];
  [content addSubview:body];
  [content addSubview:quit];

  [NSLayoutConstraint activateConstraints:@[
    [title.topAnchor constraintEqualToAnchor:content.topAnchor constant:18],
    [title.leadingAnchor constraintEqualToAnchor:content.leadingAnchor constant:20],
    [title.trailingAnchor constraintEqualToAnchor:content.trailingAnchor constant:-20],
    [body.topAnchor constraintEqualToAnchor:title.bottomAnchor constant:10],
    [body.leadingAnchor constraintEqualToAnchor:title.leadingAnchor],
    [body.trailingAnchor constraintEqualToAnchor:title.trailingAnchor],
    [quit.trailingAnchor constraintEqualToAnchor:content.trailingAnchor constant:-20],
    [quit.bottomAnchor constraintEqualToAnchor:content.bottomAnchor constant:-16],
  ]];

  [self.window makeKeyAndOrderFront:nil];
  [NSApp activateIgnoringOtherApps:YES];
}

- (void)startLaunchScript {
  char script[PATH_MAX], messages_cache[PATH_MAX], contacts_cache[PATH_MAX];
  if (!resolve_paths(script, sizeof(script), messages_cache, sizeof(messages_cache),
                     contacts_cache, sizeof(contacts_cache))) {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"MessageManager failed to launch";
    alert.informativeText = @"Could not find launch.sh inside the app bundle.";
    [alert runModal];
    [NSApp terminate:nil];
    return;
  }

  NSTask *task = [[NSTask alloc] init];
  task.executableURL = [NSURL fileURLWithPath:@"/bin/bash"];
  task.arguments = @[ [NSString stringWithUTF8String:script] ];
  task.environment = [[NSProcessInfo processInfo] environment];
  MMAppDelegate *strongSelf = self;
  task.terminationHandler = ^(NSTask *finished) {
    dispatch_async(dispatch_get_main_queue(), ^{
      // Managed mode exits after starting the server; keep the app alive.
      if (finished.terminationStatus != 0) {
        NSAlert *alert = [[NSAlert alloc] init];
        alert.messageText = @"MessageManager failed to start";
        alert.informativeText =
            @"Check ~/Library/Application Support/MessageManager/logs/launch.log";
        [alert runModal];
        [NSApp terminate:nil];
      }
      (void)strongSelf;
    });
  };

  NSError *error = nil;
  if (![task launchAndReturnError:&error]) {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"MessageManager failed to launch";
    alert.informativeText = error.localizedDescription ?: @"Unknown error";
    [alert runModal];
    [NSApp terminate:nil];
    return;
  }
  self.launchTask = task;
}

- (void)pollServer {
  // If the server dies while the control window is open, exit cleanly.
  // Poll /api/ping (not /api/health): health used to copy+COUNT chat.db and
  // could exceed this timeout on large libraries, which looked like a crash.
  static BOOL sawUp = NO;
  static NSInteger failStreak = 0;
  NSURL *url = [NSURL URLWithString:[self.baseURL stringByAppendingString:@"/api/ping"]];
  NSMutableURLRequest *req = [NSMutableURLRequest requestWithURL:url
                                                     cachePolicy:NSURLRequestReloadIgnoringLocalCacheData
                                                 timeoutInterval:2.0];
  NSURLSessionDataTask *task =
      [[NSURLSession sharedSession] dataTaskWithRequest:req
                                      completionHandler:^(NSData *data, NSURLResponse *response, NSError *err) {
                                        (void)data;
                                        BOOL up = (err == nil && [(NSHTTPURLResponse *)response statusCode] == 200);
                                        dispatch_async(dispatch_get_main_queue(), ^{
                                          if (up) {
                                            sawUp = YES;
                                            failStreak = 0;
                                            return;
                                          }
                                          if (!sawUp) {
                                            return;
                                          }
                                          failStreak += 1;
                                          // Require a few misses so a brief restart doesn't quit the app.
                                          if (failStreak >= 3) {
                                            [NSApp terminate:nil];
                                          }
                                        });
                                      }];
  [task resume];
}

- (void)requestShutdown {
  NSURL *url = [NSURL URLWithString:[self.baseURL stringByAppendingString:@"/api/shutdown"]];
  NSMutableURLRequest *req = [NSMutableURLRequest requestWithURL:url];
  req.HTTPMethod = @"POST";
  req.HTTPBody = [NSData data];
  req.timeoutInterval = 3.0;
  NSURLSessionDataTask *task =
      [[NSURLSession sharedSession] dataTaskWithRequest:req
                                      completionHandler:^(NSData *data, NSURLResponse *response, NSError *err) {
                                        (void)data;
                                        (void)response;
                                        (void)err;
                                      }];
  [task resume];
  // Brief pause so the request can leave before we tear down the process.
  usleep(250000);
}

- (void)quitApp:(id)sender {
  (void)sender;
  [self requestShutdown];
  if (self.launchTask.isRunning) {
    [self.launchTask terminate];
  }
  [NSApp terminate:nil];
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {
  (void)sender;
  [self requestShutdown];
  return YES;
}

- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender {
  (void)sender;
  [self.pollTimer invalidate];
  [self requestShutdown];
  return NSTerminateNow;
}

@end

static int run_probe_fda_cli(const char *out_path) {
  const char *home = getenv("HOME");
  if (!home || !home[0]) home = "/Users/Shared";
  char src[PATH_MAX];
  snprintf(src, sizeof(src), "%s/Library/Messages/chat.db", home);
  FILE *out = fopen(out_path && out_path[0] ? out_path : "/dev/null", "w");
  FILE *db = fopen(src, "rb");
  if (!db) {
    const char *err = (errno == EPERM || errno == EACCES)
                          ? "Permission denied"
                          : strerror(errno);
    if (out) {
      fprintf(out, "{\"ok\":false,\"detail\":\"%s\"}\n", err ? err : "Failed");
      fclose(out);
    }
    return 2;
  }
  char buf[1];
  size_t n = fread(buf, 1, 1, db);
  fclose(db);
  if (n != 1) {
    if (out) {
      fprintf(out, "{\"ok\":false,\"detail\":\"Could not read Messages database\"}\n");
      fclose(out);
    }
    return 2;
  }
  if (out) {
    fprintf(out, "{\"ok\":true,\"detail\":\"Readable\"}\n");
    fclose(out);
  }
  return 0;
}

static int run_refresh_cache_cli(void) {
  const char *home = getenv("HOME");
  if (!home || !home[0]) home = "/Users/Shared";
  char messages_cache[PATH_MAX], contacts_cache[PATH_MAX], status_path[PATH_MAX];
  snprintf(messages_cache, sizeof(messages_cache),
           "%s/Library/Application Support/MessageManager/messages-cache", home);
  snprintf(contacts_cache, sizeof(contacts_cache),
           "%s/Library/Application Support/MessageManager/contacts-cache", home);
  snprintf(status_path, sizeof(status_path),
           "%s/Library/Application Support/MessageManager/logs/cache-refresh.json",
           home);
  {
    char logs[PATH_MAX];
    snprintf(logs, sizeof(logs),
             "%s/Library/Application Support/MessageManager/logs", home);
    ensure_dir(logs);
  }
  write_progress_json(status_path, "Starting cache refresh…", 1, 0, NULL);
  int rc = refresh_messages_cache_progress(home, messages_cache, status_path);
  if (rc != 0) return rc;
  write_progress_json(status_path, "Copying Contacts…", 80, 0, NULL);
  refresh_contacts_cache(home, contacts_cache);
  write_progress_json(status_path, "Cache refresh complete", 100, 1, NULL);
  return 0;
}

int main(int argc, const char *argv[]) {
  for (int i = 1; i < argc; i++) {
    if (strcmp(argv[i], "--refresh-cache") == 0) {
      return run_refresh_cache_cli();
    }
    if (strcmp(argv[i], "--probe-fda") == 0) {
      const char *out = (i + 1 < argc) ? argv[i + 1] : "";
      return run_probe_fda_cli(out);
    }
  }
  @autoreleasepool {
    [NSApplication sharedApplication];
    [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
    MMAppDelegate *delegate = [[MMAppDelegate alloc] init];
    NSApp.delegate = delegate;
    // NSApplicationMain finishes launching (stops Dock bounce) and runs the app.
    return NSApplicationMain(argc, argv);
  }
}
