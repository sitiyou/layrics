#include <pybind11/functional.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "core/app/ApplicationController.hpp"
#include "core/types/Common.hpp"

namespace py = pybind11;

// Recursively convert a Python menu tree ({label, action?, children?} dicts)
// into C++ UiMenuItem; called on the Python thread (no GIL crossing).
static std::vector<UiMenuItem> parseMenuItems(const py::list &items) {
    std::vector<UiMenuItem> out;
    out.reserve(items.size());
    for (const py::handle &h : items) {
        py::dict d = py::cast<py::dict>(h);
        UiMenuItem item;
        item.label = py::cast<std::string>(d["label"]);
        if (d.contains("action")) {
            item.action = py::cast<std::string>(d["action"]);
        }
        if (d.contains("children")) {
            item.children = parseMenuItems(py::cast<py::list>(d["children"]));
        }
        out.push_back(std::move(item));
    }
    return out;
}

PYBIND11_MODULE(core, m) {
    m.doc() = "layrics - ASS subtitle overlay on wlr-layer-shell";

    py::class_<AppState>(m, "StateView")
        .def_readonly("paused", &AppState::paused)
        .def_readonly("hidden", &AppState::hidden)
        .def_readonly("locked", &AppState::locked)
        .def_readonly("start_time_ms", &AppState::startTimeMs)
        .def_readonly("drag_offset_x", &AppState::dragOffsetX)
        .def_readonly("drag_offset_y", &AppState::dragOffsetY)
        .def_readonly("target_fps", &AppState::targetFps);

    py::class_<ApplicationController>(m, "ApplicationController")
        .def(py::init<>())
        .def("start", &ApplicationController::start,
             py::call_guard<py::gil_scoped_release>())
        .def("stop", &ApplicationController::stop)
        .def("join", &ApplicationController::join,
             py::call_guard<py::gil_scoped_release>())
        .def("set_ass_input", &ApplicationController::setAssInput,
             py::arg("content"))
        .def(
            "set_ui_menu",
            [](ApplicationController &ctrl, py::list items) {
                ctrl.setUiMenu(parseMenuItems(items));
            },
            py::arg("items"))
        .def("set_status",
             [](ApplicationController &ctrl, py::kwargs kwargs) {
                 PendingUpdate update;
                 for (auto &[key, val] : kwargs) {
                     std::string k = py::cast<std::string>(key);
                     if (k == "paused") {
                         update.paused = py::cast<bool>(val);
                         update.mask |= PendingUpdate::PAUSED;
                     } else if (k == "hidden") {
                         update.hidden = py::cast<bool>(val);
                         update.mask |= PendingUpdate::HIDDEN;
                     } else if (k == "locked") {
                         update.locked = py::cast<bool>(val);
                         update.mask |= PendingUpdate::LOCKED;
                     } else if (k == "start_time_ms") {
                         update.startTimeMs = py::cast<int64_t>(val);
                         update.mask |= PendingUpdate::START_TIME;
                     } else if (k == "target_fps") {
                         update.targetFps = py::cast<int>(val);
                         update.mask |= PendingUpdate::TARGET_FPS;
                     } else {
                         throw std::invalid_argument("unknown status field: " +
                                                     k);
                     }
                 }
                 ctrl.setStatus(update);
             })
        .def_property_readonly(
            "state",
            [](ApplicationController &ctrl) -> const AppState & {
                return ctrl.state();
            },
            py::return_value_policy::reference_internal)
        .def(
            "poll_key_events",
            [](ApplicationController &ctrl) {
                std::vector<KeyEvent> events = ctrl.pollKeyEvents();
                py::list out;
                for (const auto &e : events) {
                    out.append(py::make_tuple(e.key, e.state, e.mods));
                }
                return out;
            })
        .def(
            "poll_ui_events",
            [](ApplicationController &ctrl) {
                return ctrl.pollUiEvents();
            });
}
