#include "configuration.h"
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>

using dramsim3::Config;

int main(int argc, char** argv) {
    if (argc != 5) return 2;

    try {
        unsetenv("FACIL_PAGE_MAP_FILE");
        Config original(argv[1], ".");

        setenv("FACIL_PAGE_MAP_FILE", argv[2], 1);
        Config mapped(argv[1], ".");

        std::ifstream f(argv[3]);
        if (!f) throw std::runtime_error("Missing fixture");

        uint64_t addr;
        int c, r, bg, b, row, col, checked = 0;

        while (f >> addr >> c >> r >> bg >> b >> row >> col) {
            auto x = mapped.AddressMapping(addr);

            if (x.channel != c || x.rank != r ||
                x.bankgroup != bg || x.bank != b ||
                x.row != row || x.column != col)
                throw std::runtime_error(
                    "Python/C++ mismatch at address " +
                    std::to_string(addr)
                );

            ++checked;
        }

        if (checked < 300)
            throw std::runtime_error("Too few samples");

        for (auto page : {0ULL, 76ULL}) {
            std::vector<unsigned char> seen(16384, 0);

            for (uint64_t i = 0; i < 16384; ++i) {
                auto x = mapped.AddressMapping(
                    (page << 21) + (i << 7)
                );

                int bank = x.bankgroup * 4 + x.bank;
                int pu = bank * 8 + x.rank * 4 + x.channel;
                int slot = ((x.row % 8) * 128 + pu) * 16
                           + x.column;

                if (x.row / 8 != (int)page ||
                    pu < 0 || pu >= 128 ||
                    x.column < 0 || x.column >= 16 ||
                    slot < 0 || slot >= 16384 ||
                    seen[slot]++)
                    throw std::runtime_error(
                        "Address alias or incorrect placement"
                    );
            }
        }

        for (uint64_t i = 0; i < 16384; ++i) {
            uint64_t a = (132ULL << 21) + (i << 7);
            auto x = original.AddressMapping(a);
            auto y = mapped.AddressMapping(a);

            if (x.channel != y.channel ||
                x.rank != y.rank ||
                x.bankgroup != y.bankgroup ||
                x.bank != y.bank ||
                x.row != y.row ||
                x.column != y.column)
                throw std::runtime_error(
                    "Conventional page mapping changed"
                );
        }

        int counts[4] = {0, 0, 0, 0};

        for (auto page : {0ULL, 76ULL, 132ULL})
            for (uint64_t i = 0; i < 32; ++i)
                ++counts[mapped.AddressMapping(
                    (page << 21) + (i << 7)
                ).channel];

        std::ofstream out(argv[4]);
        for (int n : counts) out << n << " ";
        out << "\n";

        std::cout << "PASS: " << checked
                  << " Python/C++ checks, MapID 2/3 uniqueness, "
                  << "conventional fallback\n";

    } catch (const std::exception& e) {
        std::cerr << "FAIL: " << e.what() << "\n";
        return 1;
    }
}
