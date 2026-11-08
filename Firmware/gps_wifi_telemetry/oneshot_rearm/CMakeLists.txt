cmake_minimum_required(VERSION 3.16)
set(COMPONENTS main nvs_flash __pio_env)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(rutea_oneshot_rearm)
