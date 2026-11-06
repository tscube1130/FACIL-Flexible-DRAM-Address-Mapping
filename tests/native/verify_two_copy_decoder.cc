#include "configuration.h"
#include <cstdlib>
#include <iostream>

// Report native tuples for paired addresses, with a conventional control.
int main(int argc, char** argv) {
    if (argc != 3) return 2;
    unsetenv("FACIL_PAGE_MAP_FILE");
    dramsim3::Config conventional(argv[1], ".");
    setenv("FACIL_PAGE_MAP_FILE", argv[2], 1);
    dramsim3::Config mixed(argv[1], ".");
    uint64_t pim, soc;
    while (std::cin >> pim >> soc) {
        if (!mixed.HasFACILPage(pim) || mixed.HasFACILPage(soc)) return 1;
        for (const auto& a : {mixed.AddressMapping(pim),
                              mixed.AddressMapping(soc),
                              conventional.AddressMapping(soc)}) {
            std::cout << a.channel << ' ' << a.rank << ' ' << a.bankgroup
                      << ' ' << a.bank << ' ' << a.row << ' ' << a.column << ' ';
        }
        std::cout << '\n';
    }
    return std::cin.eof() ? 0 : 1;
}
