#include "core/app/ApplicationController.hpp"

#include <cstdio>
#include <csignal>
#include <stdexcept>

static ApplicationController *gCtrl = nullptr;

static void handleSignal(int) {
    if (gCtrl) {
        gCtrl->stop();
    }
}

int main() {
    try {
        ApplicationController controller;
        gCtrl = &controller;

        signal(SIGINT, handleSignal);
        signal(SIGTERM, handleSignal);

        controller.start();

        fprintf(stderr, "[INFO] Application started. Press Ctrl+C to exit.\n");
        controller.join();

        return 0;
    } catch (const std::exception &e) {
        fprintf(stderr, "[FATAL] %s\n", e.what());
        return 1;
    }
}
