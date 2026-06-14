#include <pybind11/pybind11.h>
#include <pybind11/functional.h>

#include "core/app/ApplicationController.hpp"

namespace py = pybind11;

PYBIND11_MODULE(_layrics, m) {
    m.doc() = "layrics - ASS subtitle overlay on wlr-layer-shell";

    py::class_<ApplicationController>(m, "ApplicationController")
        .def(py::init<>())
        .def("start", &ApplicationController::start,
             py::call_guard<py::gil_scoped_release>())
        .def("stop", &ApplicationController::stop)
        .def("join", &ApplicationController::join,
             py::call_guard<py::gil_scoped_release>())
        .def("set_ass_input", &ApplicationController::setAssInput,
             py::arg("path"))
        .def("set_paused", &ApplicationController::setPaused,
             py::arg("paused"))
        .def("set_start_time", &ApplicationController::setStartTime,
             py::arg("ms"))
        .def("get_start_time", &ApplicationController::getStartTime)
        .def("set_hidden", &ApplicationController::setHidden,
             py::arg("hidden"));
}
